# CLIProxyAPI 模型上下文窗口插件

<img src="assets/logo.svg" width="104" height="104" alt="Model Context Windows 图标" align="right">

[English](README.md)

通过 C ABI v1 响应拦截接口，为 OpenAI 形状的模型列表补充配置的
`context_length`。不自动探测模型能力，不改变推理请求或服务端 token 限制。
仅使用 Go 标准库。

这是独立的社区项目，**不是 CLIProxyAPI 官方组件，也不代表上游维护者认可**。

例如将虚构模型配置为 `example-small: 32768`，对应模型条目会补充：

```json
{"id":"example-small","object":"model","context_length":32768}
```

数值由管理员配置，插件不会实测或保证模型具有该容量。

## 要求与兼容性

需要 Linux CLIProxyAPI 主机，且支持 **C ABI v1 响应拦截插件协议**；
仅支持 OpenAI 兼容接口并不代表支持此插件。构建需要 Go 1.26、C 编译器和
libc 开发头文件；离线测试需要 Python 3。共享库须匹配宿主架构和 libc。

ABI 声明核对的源码基线为上游提交
`556f50aa2adf4075303e82ccf6355efc06d3f2df`（v7 模块源码）。
1.1.1 提供 **Linux amd64 与 Linux arm64** 两个预编译共享库。amd64 版已在隔离的
CLIProxyAPI v8.0.23（提交 `d318bcc`）与 v8.0.44 宿主中加载，虚构 provider 的
`/v1/models` 返回了配置的 `context_length: 32768`。arm64 版已在真实 aarch64 机器上
用 `dlopen`/`dlsym` 验证四个插件 ABI 符号均可解析（当时没有 arm64 的 CLIProxyAPI
宿主可做端到端加载）。这是针对模型列表的集成检查，不保证所有宿主版本、架构、
provider 或客户端兼容。

## 预编译产物

| 平台 | 压缩包 |
| --- | --- |
| Linux amd64 | `models-context_<version>_linux_amd64.zip` |
| Linux arm64 | `models-context_<version>_linux_arm64.zip` |

每个压缩包根目录只有一个 `models-context.so`，`checksums.txt` 提供两者的 sha256。
不提供 macOS 产物：实际加载本插件的 CLIProxyAPI 宿主都是 Linux；macOS 用户可用下方
步骤从源码构建（`build.sh` 会自动选择 `.dylib` 后缀）。

## 构建、测试与安装

```sh
go test ./...
sh build.sh
python3 harness.py dist/models-context-v1.1.1.so
```

脚本前台构建，输出版本化 `.so` 和生成的 C 头文件至 `dist/`，不安装、不重载。
可选 Docker 构建（需要 Docker 与镜像；命令可能拉取镜像）：

```sh
docker run --rm -v "$PWD:/src" -w /src golang:1.26-bookworm sh -c 'go test ./... && sh build.sh'
```

这只会在挂载目录构建；harness 必须在能加载该架构/libc 共享库的环境运行。

构建后可选执行隔离宿主测试（需已有镜像，含 `./CLIProxyAPI` 并支持 `-local-model`）：

```sh
python3 tests/integration.py "$PWD" YOUR_LOCAL_CPA_IMAGE_ID
```

测试在工作副本写入虚构配置 `integration-config.yaml` 与 `integration-plugins/`，
用随机回环端口启动独立容器，检查 `example-model` 返回 `context_length: 32768`，
并删除测试容器。不读取生产配置，不调用推理，也不自动拉取镜像。
请使用可丢弃的工作副本；生成文件已被 Git 忽略。
宿主进程仍可能发出后台网络请求（如更新或元数据请求），此集成测试并未隔离网络。
插件本身不访问网络。两个 Python 测试脚本都要求启用断言，拒绝 `-O`、`-OO`
或 `PYTHONOPTIMIZE` 优化执行。

按宿主文档设置插件目录，将产物**重命名为 `models-context.so`**后放入目录，
确保插件 ID 与配置键一致。旧版本应移出扫描目录，避免重复候选。
按宿主文档重启，不承诺热重载。最后请求 `/v1/models` 验证字段。

```yaml
plugins:
  enabled: true
  configs:
    models-context:
      enabled: true
      priority: 1
      context_lengths:
        example-small: 32768
        example-large: 131072
        "example:local": 8192
```

示例 ID 均为虚构，请替换为实际 ID。宿主以生命周期 JSON 中 base64 编码的
`config_yaml` 传入插件配置块，也接受旧 `ConfigYAML` 拼写。
值必须是正十进制整数，可加引号。**不支持 K/M 后缀、`context-lengths`
键名、YAML 锚点或完整 YAML 语法**。
非 ASCII YAML `\xHH` 转义（大于 `\x7F`，如 `\x80`、`\xE9`）不受支持，
会被拒绝而非解码为原始字节；请使用 Unicode 字符或 `\u`/`\U` 转义。
ASCII `\xHH` 转义受支持。支持上面的缩进映射及内联 JSON：

```yaml
context_lengths: '{"example-small":32768}'
# context_lengths_json 也可用于内联 JSON。
```

## 行为与限制

- ID 精确匹配且区分大小写，不根据模型家族推断。
- 仅处理没有执行模型字段的非流式 2xx 响应。`data` 非空且每项必须包含
  非空字符串 ID 与 `object: model`；顶层 object 必须为 list 或缺省/空字符串。
- 保留上游正数 context_length（含数字字符串）；缺失、零、负数或无效值可补充。
  未配置模型不修改。保留未知 JSON 字段和整数精度；重写可改变格式和键顺序。
- 当前 ABI 输入没有用于此处的路由判定：其他返回相同列表形状的接口也可能被
  拦截。形状校验不等于证明请求路径为 `/v1/models`。
- 生命周期配置缺失或损坏时清空旧映射；无效条目忽略，空映射不改响应。
  这是宿主规范化 YAML 的有限子集解析器，不是完整 YAML 解析器。
- 无调试 probe、响应日志、网络请求或宿主回调。配置值不会与 provider 核验。

## 测试范围

Go 回归测试覆盖列表检测、字段保留、注入规则、排除条件、配置形式和旧状态
清理。ctypes harness 加载实际共享库，验证握手、信封、缓冲区释放、元数据、
生命周期及示例响应。它们是**离线测试**，不等同完整宿主集成、并发压力测试、
安全审计、客户端兼容矩阵或 provider 容量证明。宿主必须遵守 C ABI 指针及
输入缓冲区生命周期约定；无效非空指针无法安全校验。

参见 [贡献指南](CONTRIBUTING.md)、[安全说明](SECURITY.md)、
[更新记录](CHANGELOG.md) 与 [第三方声明](THIRD_PARTY_NOTICES.md)。
采用 [MIT 许可证](LICENSE)。
