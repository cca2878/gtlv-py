//! `gtlv-core` 的 Python 绑定。
//!
//! 检测框、特征向量与提示词字数原样上交 Python；指派、`w` 生成与滑动求解在 Python 层实现。
//!
//! 模型由 `gtlv-core` 经 `include_bytes!` 携带，无需模型文件或临时目录。

use std::sync::Mutex;

use gtlv_core::{Engine, PerfTimer};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

/// 一个检测框。
#[pyclass(frozen, get_all)]
pub struct Detection {
    /// 原图像素坐标 `(x_min, y_min, x_max, y_max)`。
    pub bbox: (f64, f64, f64, f64),
    pub confidence: f64,
    pub class_id: i32,
}

#[pymethods]
impl Detection {
    fn __repr__(&self) -> String {
        format!(
            "Detection(bbox={:?}, confidence={:.3})",
            self.bbox, self.confidence
        )
    }
}

/// 一次推理的完整产物。
#[pyclass(frozen, get_all)]
pub struct DetectResult {
    /// 答案格，已完成 NMS 与数量截断。
    pub detections: Vec<Py<Detection>>,
    /// 各答案格的 512 维特征，与 `detections` 一一对应且顺序一致。
    pub answer_features: Vec<Vec<f64>>,
    /// 提示词各字的 512 维特征，按自左至右排列。
    pub prompt_features: Vec<Vec<f64>>,
    /// 提示词整体框；未检出时为 `None`。
    pub prompt_box: Option<(f64, f64, f64, f64)>,
}

#[pymethods]
impl DetectResult {
    fn __repr__(&self) -> String {
        format!(
            "DetectResult(m={}, k={})",
            self.detections.len(),
            self.prompt_features.len()
        )
    }
}

/// 推理器：进程内构造一次、反复调用 `detect`。
///
/// 构造开销以模型加载与图优化为主（数百毫秒），应复用而非每次求解都新建。
/// `detect` 可从多个线程调用，内部以互斥串行化。
#[pyclass(frozen)]
pub struct Detector {
    engine: Mutex<Engine>,
}

#[pymethods]
impl Detector {
    /// 加载内置模型并构造推理器。
    #[new]
    fn new(py: Python<'_>) -> PyResult<Self> {
        // 加载不触及 Python 对象；释放 GIL 使调用方的事件循环不被阻塞。
        let engine = py
            .allow_threads(Engine::new)
            .map_err(|e| PyRuntimeError::new_err(format!("load models: {e}")))?;
        Ok(Self {
            engine: Mutex::new(engine),
        })
    }

    /// 对一张验证码图（PNG/JPEG 字节）做检测与特征提取。
    #[pyo3(signature = (image, conf_threshold = 0.5))]
    fn detect(
        &self,
        py: Python<'_>,
        image: &[u8],
        conf_threshold: f32,
    ) -> PyResult<Py<DetectResult>> {
        if image.is_empty() {
            return Err(PyValueError::new_err("empty image"));
        }
        // 推理不触及 Python 对象；释放 GIL 使调用方的协程或线程不被阻塞。
        let result = py.allow_threads(|| {
            let engine = self.engine.lock().map_err(|_| "engine mutex poisoned")?;
            let timer = PerfTimer::new(false);
            engine
                .detect_and_extract(image, conf_threshold, &timer)
                .map_err(|e| e.to_string())
        });
        let result = result.map_err(PyRuntimeError::new_err)?;

        let detections = result
            .detections
            .iter()
            .map(|d| {
                Py::new(
                    py,
                    Detection {
                        bbox: (
                            d.bbox.x_min as f64,
                            d.bbox.y_min as f64,
                            d.bbox.x_max as f64,
                            d.bbox.y_max as f64,
                        ),
                        confidence: d.confidence as f64,
                        class_id: d.class_id,
                    },
                )
            })
            .collect::<PyResult<Vec<_>>>()?;

        // 特征以 f64 上交：指派要求按 f64 累加距离，在边界处一次转换即可。
        let widen = |features: &Vec<Vec<f32>>| -> Vec<Vec<f64>> {
            features
                .iter()
                .map(|f| f.iter().map(|&v| v as f64).collect())
                .collect()
        };

        Py::new(
            py,
            DetectResult {
                detections,
                answer_features: widen(&result.answer_features),
                prompt_features: widen(&result.prompt_features),
                prompt_box: result.prompt_box.map(|b| {
                    (
                        b.x_min as f64,
                        b.y_min as f64,
                        b.x_max as f64,
                        b.y_max as f64,
                    )
                }),
            },
        )
    }
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Detector>()?;
    m.add_class::<DetectResult>()?;
    m.add_class::<Detection>()?;
    m.add("__doc__", "gtlv-core 推理引擎的绑定。")?;
    Ok(())
}
