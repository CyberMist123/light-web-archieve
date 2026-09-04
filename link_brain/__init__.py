"""link_brain — light-web-archieve 的归档基座。

V1 只处理小红书。设计约束见 docs/TASKBOOK.md，数据格式见 docs/FORMAT.md。
"""

__version__ = "0.1.0"

# vault 布局常量（唯一真相；其余模块从这里取）
VAULT_DIRNAME = "vault"
ARCHIVE_DIRNAME = "_archive"
VISIBLE_SUBDIR = ("Web", "Xiaohongshu")
INDEX_DB_NAME = "index.db"
RAW_VERSION_PREFIX = "v"
