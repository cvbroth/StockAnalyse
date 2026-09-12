"""旧版兼容入口；新代码请从app.storage.sqlite导入。"""

if __package__:
    from .storage.sqlite import *  # type: ignore[import-not-found] # noqa: F401,F403
else:
    from storage.sqlite import *  # type: ignore[import-not-found] # noqa: F401,F403
