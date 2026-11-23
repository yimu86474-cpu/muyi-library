from pathlib import Path, PurePosixPath

from .database import LibraryDatabase


class AssetAccessError(Exception):
    pass


def resolve_registered_asset(database: LibraryDatabase, asset_id: str) -> Path:
    if not asset_id or any(character not in "0123456789abcdef" for character in asset_id):
        raise AssetAccessError("无效素材编号")
    try:
        asset = database.get_asset_record(asset_id)
        source = database.get_source(asset["source_id"])
    except KeyError as error:
        raise AssetAccessError("素材未登记") from error
    root = Path(source["root_path"]).resolve()
    candidate = root / asset["relative_path"]
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise AssetAccessError("原文件不存在或已离开来源目录") from error
    if not resolved.is_file():
        raise AssetAccessError("素材不是文件")
    return resolved


def resolve_registered_folder(
    database: LibraryDatabase, source_id: str, relative_folder: str = ""
) -> Path:
    raw = str(relative_folder or "").strip().strip("/")
    if raw:
        folder = PurePosixPath(raw)
        if folder.is_absolute() or any(part in ("", ".", "..") for part in folder.parts):
            raise ValueError("项目文件夹路径不合法")
        normalized = "/".join(folder.parts)
    else:
        normalized = ""
    try:
        source = database.get_source(str(source_id or ""))
    except KeyError as error:
        raise AssetAccessError("素材来源未登记") from error
    root = Path(source["root_path"]).resolve()
    candidate = root / normalized if normalized else root
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise AssetAccessError("文件夹不存在或已离开来源目录") from error
    if not resolved.is_dir():
        raise AssetAccessError("登记位置不是文件夹")
    return resolved
