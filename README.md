# gtlv-py

gt V3 点选与滑动验证码的 Python 本地求解库。**模型推理经 PyO3 交由 `gtlv-core`，其余全部为 Python**：指派、`w` 参数生成、滑动求解与协议编排。求解本身不依赖网络，可用于离线图像。

要求 CPython 3.10 及以上。

## 主要能力

- **点选求解**：复用 `gtlv-core` 的 YOLO 检测和 Siamese 特征提取，根据提示框宽高比确定提示字数，再以矩形最优指派跳过答案区中的干扰字。
- **滑动求解**：还原乱序背景、识别缺口、生成拟人轨迹并完成 gt 轨迹编码。
- **本地加密**：生成点选和滑动 V3 `w` 参数，包括 AES-CBC、RSA 和 gt 自定义 Base64。
- **异步编排**：自动判断验证码类型、并发下载滑动背景、补足验证时延、按规则换图重试，并返回类型化结果和异常。
- **自包含分发**：生产模型由 `gtlv-core` 通过 `include_bytes!` 内嵌。wheel 不需要模型目录、临时目录、ONNX Runtime 或额外的系统推理动态库。
- **类型支持**：包内包含 `.pyi` 和 `py.typed`，可供 mypy 等类型检查器使用。

`Client` 默认使用标准库（`urllib`，见 `gtlv/_http.py`），无需 HTTP 依赖；也支持注入兼容的异步 HTTP 客户端（httpx/aiohttp），方便配置代理、接入现有会话或进行离线协议测试。

运行期依赖只有两项：`cryptography` 用于 `w` 所需的 AES-CBC 与 RSA，`pillow` 用于滑动背景的解码、重排与差分。

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
Python 求解层
    ├─ gtlv.solver              前置校验 + 指派 → 点击坐标
    ├─ gtlv.matching            矩形最优指派
    ├─ gtlv.slide               背景还原、缺口识别、轨迹生成与编码
    └─ gtlv.crypto              点选/滑动 w
           │
           ▼
PyO3 扩展 gtlv._native
    └─ Detector / gtlv-core     检测框 + 特征向量 + 提示字数
```

`Solver` 的构造需加载模型，耗时数百毫秒，应在进程内构造一次并复用；其内部以互斥锁串行化推理，可从多个线程调用。`Client` 在首次遇到点选验证码时才懒加载并缓存 `Solver`，只处理滑动验证码的进程不承担这项开销。

## 安装

从 PyPI 安装：

```bash
python -m pip install gtlv
```

从源码安装：

```bash
python -m pip install 'maturin>=1,<2'
python -m maturin develop --release
```

构建产物是与目标平台匹配的原生 wheel，并非 `py3-none-any` 通用 wheel。它针对 CPython 稳定 ABI编译（`cp310-abi3`），同一个 wheel 适用于 3.10 及以上的所有版本。

## 本地原语

本地 API 不发起网络请求，可直接用于离线图片、定制编排或测试：

```python
from gtlv import Solver, solve_slide
from gtlv.crypto import click_w, slide_w  # 仅在自行编排协议时需要

gt = "..."
challenge = "..."

# 点选：Solver 应在进程内长期复用。
solver = Solver()
click = solver.solve(click_image_bytes)
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

模型加载与推理期间均释放 GIL，`Client` 又通过 `asyncio.to_thread()` 调用二者，因此异步程序的事件循环不会被阻塞。

公开的本地接口如下：

| 接口 | 作用 |
|---|---|
| `Solver()` | 加载内嵌模型；应一次构造、反复使用 |
| `Solver.solve(image, conf_threshold=0.1)` | 求解一张 PNG/JPEG 点选图，返回 `ClickResult` |
| `solve_slide(bg, fullbg)` | 求解两张乱序滑动背景，返回 `SlideResult` |
| `gtlv.crypto.click_w(coords, gt, challenge)` | 根据有序点击坐标生成点选 `w` |
| `gtlv.crypto.slide_w(distance, encrypted_track, gt, challenge, c, s)` | 生成滑动 `w` |

`w` 的载荷含与提交时刻绑定的时延锚点，须在生成后随即提交。这两个函数位于 `gtlv.crypto`，供自行编排整套协议时调用。

参数为空、距离非正等调用错误会抛出 `ValueError`；图像无法求解（解码失败、未检出目标、缺口未定位）会抛出 `UnsolvableImageError`，调用方应更换图像重试。

## 完整 V3 流程

`gt`/`challenge` 可由库获取，也可由调用方提供。两者走同一条求解与重试路径，行为一致。

### 由库获取（常见）

业务登记接口若为 Bilibili 形状（返回 `data.geetest.gt` 与 `data.geetest.challenge`），可一步拿到结果：

```python
async with Client(max_attempts=3) as client:
    result = await client.solve_registered()              # 使用内置 Bilibili 登记地址
    result = await client.solve_registered(register_url)  # 或指定同形状的地址
```

### 由调用方提供

登记接口形状不同，或 `gt`/`challenge` 已在别处取得时，直接传入：

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
| `gt` | 本次使用的 gt 站点 ID |
| `challenge` | 最终验证使用的 challenge |
| `validate` | gt 验证结果 |
| `captcha_type` | `"click"` 或 `"slide"` |
| `seccode` | `validate + "|jordan"` |

滑动流程会从 gt 获取新的 challenge。业务提交必须使用 `result.challenge` 和`result.validate` 这一对，不能继续提交传给 `solve()` 的旧 challenge。`result.as_dict()` 返回常见的`challenge`、`validate`、`seccode` 三字段，可避免配错。

若只想单独取 challenge，`fetch_challenge()` 返回可解包的 `Challenge`：

```python
gt, challenge = await client.fetch_challenge(register_url)
```

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

- `click_solver` 可注入任何提供同步 `solve(image)` 方法的兼容对象。显式传入 `None` 后，遇到点选会抛出 `SolverRequiredError`。
- `http_client` 需提供异步 `get(url, params=...)`；其响应对象需按使用场景提供`raise_for_status()`、`json()`、`text` 和 `content`。注入的客户端由调用方持有，`Client.aclose()`不会关闭它。
- 未注入 `http_client` 时使用内置标准库客户端，它会带浏览器 `User-Agent`（B 站登记端点对未知客户端返回 412）。该客户端无连接池、无需释放，但仍建议用 `async with` 保持写法一致。
- `max_attempts` 小于 1 时会按 1 处理。默认只尝试一次，需要换图重试时应显式调大。
- `verify_delay` 是从本轮图片下载开始到提交 verify 的总时长下限；下载、推理和加密耗时会计入，不会在求解完成后再固定睡满 2 秒。传入负值时按 0 处理。

## 重试与异常

**默认 `max_attempts=1`，即只尝试一次，失败按类型化异常如实抛出。** 需要重试须显式调大。

重试不依赖重新登记，因此 `gt`/`challenge` 由谁获取并不影响其行为：点选经 `refresh.php` 换图后仍用同一个 challenge，滑动则重新获取整组参数与新 challenge。服务端拒绝一次后换图重试仍可能通过。

重试规则：

- 点选本地求解失败或服务端拒绝答案时，经 `refresh.php` 换图后重试；
- 滑动本地求解失败或服务端拒绝答案时，重新获取整组参数、图片和新 challenge；
- HTTP、JSON/JSONP、字段缺失等协议错误不触发重试，直接抛出；
- 达到 `max_attempts` 后抛出最后一次可重试错误。

库定义的异步客户端异常层级：

```text
GtlvError
├─ ProtocolError
├─ UnsolvableImageError
├─ VerificationError
├─ SolverRequiredError
└─ UnsupportedCaptchaTypeError
```

`VerificationError` 提供服务端的 `result` 和 `message` 属性；`UnsupportedCaptchaTypeError`提供 `captcha_type` 属性。参数为空等编程错误仍使用标准 `ValueError`。响应状态码失败会包装为`ProtocolError`；HTTP 客户端在 `get()` 内直接抛出的连接、超时等传输异常则保持原类型向上传播。

## 开发与验证

需要 CPython 3.10+、maturin 和 Rust。仓库通过 `rust-toolchain.toml` 固定 Rust `1.96.1`，rustup会自动选择该工具链。

推理与内嵌模型来自 [`gtlv-core`](https://github.com/cca2878/gtlv-core)，以固定 revision 的 git依赖引入，由 cargo 自动获取，无需另行检出。该 revision 决定了内置的模型版本，升级须显式修改`Cargo.toml`。

```bash
python -m pip install 'maturin>=1,<2' 'mypy>=1.19'

make fmt             # cargo fmt
make lint            # fmt check + clippy -D warnings + mypy
make develop         # release 模式安装扩展到当前 Python 环境
make test            # develop + Python unittest
make wheel           # release wheel，输出到 target/wheels/
```

Makefile 不探测仓库外的虚拟环境，统一使用可覆盖的 `PYTHON` 和 `CARGO`：

```bash
make PYTHON=python3.12 CARGO=cargo test
```

测试全部不访问网络。客户端测试使用注入的假 HTTP 客户端，覆盖点选/滑动分派、懒加载、换图重试、challenge 更新与协议错误；其余覆盖矩形指派、滑动背景还原与轨迹编码、gt 自定义 Base64 与 `w`载荷的键序。其中滑动编码与背景还原与 Go 实现的输出逐字节比对。

## 许可

[AGPL-3.0-only](./LICENSE)。点选识别思路参考 CaptchaBreaker；`w` 参数、滑动求解和协议编排沿用gtlv 系项目中来自 biliTicker_gt 的 AGPL-3.0 实现。
