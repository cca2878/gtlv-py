//! gtlv 的 Python 绑定（PyO3 本地核）。
//!
//! 只导出纯本地原语：点选推理、滑动求解、w 加密。网络与编排（2s 时延锚点、换图重试）在
//! Python 侧，故此处不含 reqwest/TLS。模型由 `gtlv-core` 经 `include_bytes!` 携带，
//! 无需模型文件或临时目录。

mod crypto;
mod matching;
mod slide;

use std::sync::Mutex;

use gtlv_core::{Engine, PerfTimer};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

/// 一次点选求解的结果。
#[pyclass(frozen, get_all)]
pub struct ClickResult {
    /// 点击坐标（图像像素，按提示词左→右序＝**提交顺序**）。
    pub coords: Vec<(f64, f64)>,
    /// 各次匹配的置信度 `1/(1+distance)`，与 coords 同序（用于诊断/路由）。
    pub confidences: Vec<f64>,
    /// 提示词字数 k（由提示框长宽比标定，非答案格数）。
    pub k: usize,
    /// 检测到的答案格数 m（含干扰字，可 > k）。
    pub m: usize,
}

#[pymethods]
impl ClickResult {
    fn __repr__(&self) -> String {
        format!(
            "ClickResult(k={}, m={}, coords={:?})",
            self.k, self.m, self.coords
        )
    }
}

/// 点选求解器：进程内构造一次、反复调用 `solve`。
///
/// 构造开销以 tract 的 optimize 为主（数百毫秒），别每次求解都新建。
/// `solve` 可从多个线程调用，内部以互斥串行化。
#[pyclass(frozen)]
pub struct Solver {
    engine: Mutex<Engine>,
}

#[pymethods]
impl Solver {
    /// 加载内嵌模型并构造求解器。
    #[new]
    fn new() -> PyResult<Self> {
        let engine =
            Engine::new().map_err(|e| PyRuntimeError::new_err(format!("load models: {e}")))?;
        Ok(Self {
            engine: Mutex::new(engine),
        })
    }

    /// 求解一张点选验证码图（PNG/JPEG 字节），返回按提交顺序排列的点击坐标。
    ///
    /// 失败即抛异常（图不可解，调用方应换图重试）：
    /// 提示框缺失 / 无答案格 / k 超出 [2,4] / 答案格数不足以覆盖 k 个目标。
    #[pyo3(signature = (image, conf_threshold = 0.5))]
    fn solve(&self, py: Python<'_>, image: &[u8], conf_threshold: f32) -> PyResult<ClickResult> {
        if image.is_empty() {
            return Err(PyValueError::new_err("empty image"));
        }
        // 推理不碰 Python 对象，释放 GIL 让调用方的协程/线程继续推进。
        let result = py.allow_threads(|| {
            let engine = self.engine.lock().map_err(|_| "engine mutex poisoned")?;
            let timer = PerfTimer::new(false);
            engine
                .detect_and_extract(image, conf_threshold, &timer)
                .map_err(|e| e.to_string())
        });
        let result = result.map_err(PyRuntimeError::new_err)?;

        // 前置校验，逐条对应 gtlv-core/docs/matching.md 的契约。
        let m = result.detections.len();
        let k = result.prompt_features.len();
        if result.prompt_box.is_none() {
            return Err(PyRuntimeError::new_err("no prompt box detected"));
        }
        if m == 0 {
            return Err(PyRuntimeError::new_err("no answer boxes detected"));
        }
        if !(2..=4).contains(&k) {
            return Err(PyRuntimeError::new_err(format!(
                "prompt char count out of range: k={k}"
            )));
        }
        if m < k {
            return Err(PyRuntimeError::new_err(format!(
                "detection missed targets: {m} tiles < {k} targets"
            )));
        }
        if result.answer_features.len() != m {
            return Err(PyRuntimeError::new_err(format!(
                "feature count mismatch: {} features for {m} detections",
                result.answer_features.len()
            )));
        }

        let matches = matching::assign(&result.prompt_features, &result.answer_features);
        if matches.is_empty() {
            return Err(PyRuntimeError::new_err("assignment produced no matches"));
        }

        let mut coords = Vec::with_capacity(matches.len());
        let mut confidences = Vec::with_capacity(matches.len());
        for mt in &matches {
            let b = &result.detections[mt.answer_index].bbox;
            coords.push((
                (b.x_min as f64 + b.x_max as f64) / 2.0,
                (b.y_min as f64 + b.y_max as f64) / 2.0,
            ));
            confidences.push(1.0 / (1.0 + mt.distance));
        }
        Ok(ClickResult {
            coords,
            confidences,
            k,
            m,
        })
    }
}

/// 一次滑动求解的结果。
#[pyclass(frozen, get_all)]
pub struct SlideResult {
    /// 缺口相对滑块起点的水平位移（还原后 260px 坐标系）。
    pub distance: i32,
    /// 极验特有编码后的拟人滑动轨迹。
    pub encrypted_track: String,
}

#[pymethods]
impl SlideResult {
    fn __repr__(&self) -> String {
        format!(
            "SlideResult(distance={}, encrypted_track={:?})",
            self.distance, self.encrypted_track
        )
    }
}

/// 纯本地求解滑动验证码。
///
/// `bg` 是带缺口的乱序背景图，`fullbg` 是完整乱序背景图；均接受 JPEG/PNG 字节。
#[pyfunction]
fn solve_slide(py: Python<'_>, bg: &[u8], fullbg: &[u8]) -> PyResult<SlideResult> {
    if bg.is_empty() || fullbg.is_empty() {
        return Err(PyValueError::new_err("bg and fullbg must not be empty"));
    }
    let result = py
        .allow_threads(|| slide::solve(bg, fullbg))
        .map_err(PyRuntimeError::new_err)?;
    Ok(SlideResult {
        distance: result.distance,
        encrypted_track: result.encrypted_track,
    })
}

/// 由点选坐标计算极验 V3 `w` 参数。
#[pyfunction]
fn click_w(coords: Vec<(f64, f64)>, gt: &str, challenge: &str) -> PyResult<String> {
    if coords.is_empty() {
        return Err(PyValueError::new_err("coords must not be empty"));
    }
    if gt.is_empty() || challenge.is_empty() {
        return Err(PyValueError::new_err("gt and challenge must not be empty"));
    }
    crypto::click_w(&coords, gt, challenge).map_err(PyRuntimeError::new_err)
}

/// 由滑动距离和轨迹计算极验 V3 `w` 参数。
#[pyfunction]
fn slide_w(
    distance: i32,
    encrypted_track: &str,
    gt: &str,
    challenge: &str,
    c: Vec<u8>,
    s: &str,
) -> PyResult<String> {
    if distance <= 0 {
        return Err(PyValueError::new_err("distance must be positive"));
    }
    if encrypted_track.is_empty() || gt.is_empty() || challenge.is_empty() {
        return Err(PyValueError::new_err(
            "encrypted_track, gt and challenge must not be empty",
        ));
    }
    crypto::slide_w(distance, encrypted_track, gt, challenge, &c, s)
        .map_err(PyRuntimeError::new_err)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Solver>()?;
    m.add_class::<ClickResult>()?;
    m.add_class::<SlideResult>()?;
    m.add_function(wrap_pyfunction!(solve_slide, m)?)?;
    m.add_function(wrap_pyfunction!(click_w, m)?)?;
    m.add_function(wrap_pyfunction!(slide_w, m)?)?;
    m.add(
        "__doc__",
        "Pure-local GeeTest V3 solving and w-generation primitives.",
    )?;
    Ok(())
}
