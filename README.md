# gtlv-py

极验（GeeTest）V3 点选与滑动验证码的 Python 本地求解库。项目采用
**Rust/PyO3 本地原语 + Python async 协议编排**的分层方式：模型推理、图像处理和 `w` 参数生成可
完全离线运行，网络请求、重试和业务接入则保留在 Python 层。

当前版本为 `0.1.0`，要求 CPython 3.9+。

## 主要能力

- **点选求解**：复用 `gtlv-core` 的 YOLO 检测和 Siamese 特征提取，根据提示框宽高比确定
  提示字数，再以矩形最优指派跳过答案区中的干扰字。
- **滑动求解**：还原乱序背景、识别缺口、生成拟人轨迹并完成极验轨迹编码。
- **本地加密**：生成点选和滑动 V3 `w` 参数，包括 AES-CBC、RSA 和极验自定义 Base64。
- **异步编排**：自动判断验证码类型、并发下载滑动背景、补足验证时延、按规则换图重试，并返回
  类型化结果和异常。
- **自包含分发**：生产模型由 `gtlv-core` 通过 `include_bytes!` 内嵌。wheel 不需要模型目录、
  临时目录、ONNX Runtime 或额外的系统推理动态库。
- **类型支持**：包内包含 `.pyi` 和 `py.typed`，可供 mypy 等类型检查器使用。

Rust 扩展不包含网络栈。`Client` 默认使用标准库（`urllib`，见 `gtlv/_http.py`）——**运行期零第三方
Python 依赖**；也支持注入兼容的异步 HTTP 客户端（httpx/aiohttp），方便配置代理、接入现有会话或
进行完全离线的协议测试。

## 架构

```text
业务登记接口
    │ gt + challenge
    ▼
Python async Client（唯一网络层）
    ├─ 类型探测、参数/图片获取、verify、时延与重试
    └─ asyncio.to_thread
           │
           ▼
PyO3 本地扩展 gtlv._native
    ├─ Solver / gtlv-core       点选推理
    ├─ matching.rs              矩形最优指派
    ├─ slide.rs                 滑动求解与轨迹
    └─ crypto.rs                点选/滑动 w
```

点选 `Solver` 的模型加载和 tract 优化有明显的一次性开销，因此应在进程内构造一次并复用。它内部以
互斥锁串行化推理，可安全地从多个线程调用。`Client` 默认会在首次遇到点选验证码时懒加载并缓存一个
`Solver`；只处理滑动验证码的进程不会承担模型加载开销。

## 安装

发布到包索引后可安装：

```bash
python -m pip install gtlv   # 无需任何额外依赖，网络层走标准库
```

只调用本地原语或自行注入 HTTP 客户端时不需要 `client` extra。

从源码安装时，`gtlv-py` 当前通过相邻的 `../gtlv-core` path dependency 构建，因此目录需保持为：

```text
gtlv-core/
gtlv-py/
```

```bash
cd gtlv-py
python -m pip install 'maturin>=1,<2'
python -m maturin develop --release
```

生成的是与 Python 版本和目标平台匹配的原生 wheel，并非 `py3-none-any` 通用 wheel。独立发布前应将
`gtlv-core` 切换为锁定 revision 的远程依赖，避免构建依赖当前工作区布局。

## 本地原语

本地 API 不发起网络请求，可直接用于离线图片、定制编排或测试：

```python
from gtlv import Solver, click_w, solve_slide, slide_w

gt = "..."
challenge = "..."

# 点选：Solver 应在进程内长期复用。
solver = Solver()
click = solver.solve(click_image_bytes, conf_threshold=0.5)
print(click.coords)        # 按提示词从左到右排列的提交坐标
print(click.confidences)   # 与 coords 同序
print(click.k, click.m)    # 提示字数、检测到的答案格数
click_payload = click_w(click.coords, gt, challenge)

# 滑动：输入带缺口背景和完整背景的原始乱序 JPEG/PNG。
slide = solve_slide(bg_bytes, fullbg_bytes)
slide_payload = slide_w(
    slide.distance,
    slide.encrypted_track,
    gt,
    slide_challenge,
    c,
    s,
)
```

`Solver.solve()` 和 `solve_slide()` 在 Rust 计算期间释放 GIL。async 客户端还会通过
`asyncio.to_thread()` 调用它们，避免耗时的本地计算占用事件循环线程。

公开的本地接口如下：

| 接口 | 作用 |
|---|---|
| `Solver()` | 加载内嵌模型；应一次构造、反复使用 |
| `Solver.solve(image, conf_threshold=0.5)` | 求解一张 PNG/JPEG 点选图，返回 `ClickResult` |
| `solve_slide(bg, fullbg)` | 求解两张乱序滑动背景，返回 `SlideResult` |
| `click_w(coords, gt, challenge)` | 根据有序点击坐标生成点选 `w` |
| `slide_w(distance, encrypted_track, gt, challenge, c, s)` | 生成滑动 `w` |

参数为空、距离非正等调用错误会抛出 `ValueError`；图片解码、模型加载或求解失败会抛出
`RuntimeError`。

## 完整 V3 流程

`gt` 和 `challenge` 通常由业务自己的登记接口签发：

```python
import asyncio

from gtlv import Client


async def main() -> None:
    gt = "..."
    challenge = "..."

    async with Client(max_attempts=3) as client:
        result = await client.solve(gt, challenge)

    # result.as_dict() 可直接交给 Bilibili 形状的业务提交接口。
    await login(**result.as_dict())


asyncio.run(main())
```

`solve()` 返回不可变的 `Validation`：

| 字段 | 含义 |
|---|---|
| `gt` | 本次使用的极验站点 ID |
| `challenge` | 最终验证使用的 challenge |
| `validate` | 极验验证结果 |
| `captcha_type` | `"click"` 或 `"slide"` |
| `seccode` | `validate + "|jordan"` |

滑动流程会从极验获取新的 challenge。业务提交必须使用 `result.challenge` 和
`result.validate` 这一对，不能继续提交传给 `solve()` 的旧 challenge。`result.as_dict()` 返回常见的
`challenge`、`validate`、`seccode` 三字段，可避免配错。

### 从登记接口开始

对于返回 `data.geetest.gt` 和 `data.geetest.challenge` 的 Bilibili 形状接口，可以使用便利方法：

```python
async with Client(max_attempts=3) as client:
    issued = await client.fetch_challenge(register_url)
    result = await client.solve(issued.gt, issued.challenge)

    # 使用内置 Bilibili 公共登记地址时，可合并为一步：
    result = await client.solve_registered()
```

`Challenge` 也支持解包：

```python
gt, challenge = await client.fetch_challenge(register_url)
```

旧名称 `V3Client`、`register()` 和 `get_validate()` 仍保留用于兼容。新代码应优先使用
`Client`、`fetch_challenge()` 和 `solve()`；`get_validate()` 只返回裸 `validate` 字符串，会丢失
滑动流程最终使用的新 challenge。

## Client 配置

```python
Client(
    click_solver=...,            # 默认懒加载内嵌 Solver；None 表示禁用点选
    http_client=...,             # 默认用标准库客户端（urllib + 线程池）
    get_base_url="https://api.geetest.com",
    visit_base_url="http://api.geevisit.com",
    max_attempts=1,
    verify_delay=2.0,
    timeout=15.0,                # 仅用于默认标准库客户端
)
```

- `click_solver` 可注入任何提供同步 `solve(image)` 方法的兼容对象。显式传入 `None` 后，遇到点选会
  抛出 `SolverRequiredError`。
- `http_client` 需提供异步 `get(url, params=...)`；其响应对象需按使用场景提供
  `raise_for_status()`、`json()`、`text` 和 `content`。注入的客户端由调用方持有，`Client.aclose()`
  不会关闭它。
- 未注入 `http_client` 时使用内置标准库客户端，它会带浏览器 `User-Agent`（B 站登记端点对未知
  客户端返回 412）。该客户端无连接池、无需释放，但仍建议用 `async with` 保持写法一致。
- `max_attempts` 小于 1 时会按 1 处理。默认只尝试一次，需要换图重试时应显式调大。
- `verify_delay` 是从本轮图片下载开始到提交 verify 的总时长下限；下载、推理和加密耗时会计入，
  不会在求解完成后再固定睡满 2 秒。传入负值时按 0 处理。

## 重试与异常

重试范围刻意保持收窄：

- 点选本地求解失败，或服务端明确拒绝答案时，通过 `refresh.php` 换图后重试；
- 滑动本地求解失败，或服务端明确拒绝答案时，重新获取整组参数、图片和新 challenge；
- HTTP、JSON/JSONP、字段缺失和其他协议错误不会被当成识别失败而静默重试；
- 达到 `max_attempts` 后抛出最后一次可重试错误。

库定义的异步客户端异常层级：

```text
GtlvError
├─ ProtocolError
├─ VerificationError
├─ SolverRequiredError
└─ UnsupportedCaptchaTypeError
```

`VerificationError` 提供服务端的 `result` 和 `message` 属性；
`UnsupportedCaptchaTypeError` 提供 `captcha_type` 属性。参数为空等编程错误仍使用标准
`ValueError`，未安装默认客户端依赖时会抛出带安装提示的 `ImportError`。响应状态码失败会包装为
`ProtocolError`；HTTP 客户端在 `get()` 内直接抛出的连接、超时等传输异常则保持原类型向上传播。

## 开发与验证

需要 CPython 3.9+、maturin 和 Rust。仓库通过 `rust-toolchain.toml` 固定 Rust `1.96.1`，rustup
会自动选择该工具链。

```bash
python -m pip install 'maturin>=1,<2' 'mypy>=1.19'

make fmt             # cargo fmt
make lint            # fmt check + clippy -D warnings + mypy
make test-rust       # Rust 单元测试
make develop         # release 模式安装扩展到当前 Python 环境
make test-python     # Python unittest
make wheel           # release wheel，输出到 target/wheels/
make test            # test-rust + develop + test-python
```

Makefile 不探测仓库外的虚拟环境，统一使用可覆盖的 `PYTHON` 和 `CARGO`：

```bash
make PYTHON=python3.12 CARGO=cargo test
```

Python 客户端测试使用注入的假 HTTP 客户端，不访问真实网络，覆盖点选/滑动分派、懒加载、换图重试、
challenge 更新、兼容 API 和协议错误。Rust 测试覆盖矩形指派、滑动背景与轨迹、极验自定义 Base64，
以及点选/滑动两类 `w` 的基本结构。

## 许可

[AGPL-3.0-only](./LICENSE)。点选识别思路参考 CaptchaBreaker；`w` 参数、滑动求解和协议编排沿用
gtlv 系项目中来自 biliTicker_gt 的 AGPL-3.0 实现。
