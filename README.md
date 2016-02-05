# git-annex-remote-qcloud

git-annex external special remote protocol for qcloud (Tencent Cloud).

Since the potential users are all Chinese, so the guide is written in Chinese.

腾讯云对象存储服务 (COS) 免费 50G，且 API 和 SDK 文档齐全 (相对于某熊厂来讲)，所以拿来做网盘做存储或者备份都是不错的选择。

假定读者对 [git-annex](https://git-annex.branchable.com/) 很熟悉。`git-annex-remote-cloud` 实现了 `git-annex` 的 [external special remote protocol](https://git-annex.branchable.com/special_remotes/external/)，于是可以利用 `git` 和 `git-annex` 将文件备份在 `qcloud` 云端。

## 安装

```bash
$ pip install --user git+https://github.com/foreverbell/git-annex-remote-qcloud
```

## 使用说明

```bash
$ mkdir playground && cd playground
$ export QCLOUD_CREDENTIALS='~/.qcloud'
$ git init
$ git annex init
$ git annex initremote qcloud type=external externaltype=qcloud encryption=none folder=music
$ git annex add "Blowing in the Wind.m4a"
$ git annex move . --to=qcloud   # upload to qcloud and delete local copy
$ git annex get . --from=qcloud  # download from qcloud
```

`~/.qcloud` 为配置文件，样例如下 (注意: qcloud 不提供建立 bucket 的 API，所以 bucket 需事先建好)。

```
app_id = 23333333
secret_id = you_secret_id
secret_key = B10wing_in_tHe_winD
bucket = annex
```

## References

1. https://git-annex.branchable.com/design/external_special_remote_protocol
2. https://github.com/tochev/git-annex-remote-pcloud
3. https://github.com/tencentyun/cos-python-sdk
