"""原子 Parquet 分页落盘、SQLite 断点及只读质量报告。"""

import fcntl
import hashlib
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tradefoundry.market import INSTRUMENTS, INTERVALS, Bar, validate_bar
from tradefoundry.okx import DataError, PublicClient
from tradefoundry.store import encode

SCHEMA_VERSION = "okx-ohlcv-v1"
SOURCE = "OKX:/api/v5/market/history-candles"
PRICE_FIELDS = ("open", "high", "low", "close", "volume_contracts", "volume_base", "volume_quote")
SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("ms", tz="UTC")),
        ("available_at", pa.timestamp("us", tz="UTC")),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        *[(key, pa.float64()) for key in PRICE_FIELDS],
        ("source", pa.string()),
        ("availability_basis", pa.string()),
        ("raw_json", pa.string()),
    ]
)


def milliseconds(time: datetime) -> int:
    if time.tzinfo is None or time.utcoffset().total_seconds() != 0:
        raise DataError("时间须显式为 UTC")
    if time.microsecond % 1000:
        raise DataError("接口时间不能含亚毫秒精度")
    return int(time.timestamp() * 1000)


def parse_page(raw: list, interval: str, observed_at: datetime) -> tuple[list[dict], list[int]]:
    if interval not in INTERVALS:
        raise DataError("不支持的周期")
    result, timestamps = [], []
    for row in raw:
        if not isinstance(row, list) or len(row) != 9 or row[8] not in {"0", "1"}:
            raise DataError("历史 K 线须为 9 字段且含合法 confirm")
        try:
            ts = int(row[0])
            timestamp = datetime.fromtimestamp(ts / 1000, UTC)
            values = [float(value) for value in row[1:8]]
        except (TypeError, ValueError, OverflowError, OSError) as error:
            raise DataError("K 线时间或数值无法解析") from error
        if not all(math.isfinite(value) for value in values) or min(values[4:]) < 0:
            raise DataError("K 线含非法价格或成交量")
        bar = Bar(timestamp, max(observed_at, timestamp + INTERVALS[interval]), *values[:5])
        validate_bar(bar, interval)
        timestamps.append(ts)
        if row[8] == "0":
            continue
        if timestamp + INTERVALS[interval] > observed_at:
            raise DataError("confirm=1 却尚未到收盘时间，拒绝未来行情")
        result.append(
            {
                "timestamp": timestamp,
                "available_at": observed_at,
                "observed_at": observed_at,
                **dict(zip(PRICE_FIELDS, values, strict=True)),
                "source": SOURCE,
                "availability_basis": "observed_at_only_historical_release_unknown",
                "raw_json": encode(row),
            }
        )
    return result, timestamps


class Warehouse:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "catalog.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS downloads (
                id TEXT PRIMARY KEY, instrument TEXT NOT NULL, interval TEXT NOT NULL,
                start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, cursor INTEGER NOT NULL,
                state TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS instrument_snapshots (
                id TEXT PRIMARY KEY, instrument TEXT NOT NULL, payload TEXT NOT NULL
            )""")

    def directory(self, instrument, interval):
        if instrument not in INSTRUMENTS or interval not in INTERVALS:
            raise DataError("不支持的标的或周期")
        return self.root / instrument / interval

    @contextmanager
    def lock(self, instrument, interval):
        directory = self.directory(instrument, interval)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".download.lock").open("a") as file:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise DataError("该数据分区已有下载进程，请稍后恢复") from error
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)

    def rows(self, instrument, interval) -> list[dict]:
        unique = {}
        for path in sorted(self.directory(instrument, interval).glob("*.parquet")):
            table = pq.read_table(path)
            if table.schema != SCHEMA:
                raise DataError(f"Parquet schema 不兼容：{path.name}")
            page = table.to_pylist()
            if hashlib.sha256(encode(page).encode()).hexdigest() != path.stem:
                raise DataError(f"Parquet 内容哈希不匹配：{path.name}")
            for row in page:
                timestamp = row["timestamp"]
                previous = unique.get(timestamp)
                if previous and any(previous[key] != row[key] for key in PRICE_FIELDS):
                    raise DataError(f"同时间行情发生冲突，需独立审查：{timestamp}")
                if previous is None or row["observed_at"] < previous["observed_at"]:
                    unique[timestamp] = row
        return [unique[key] for key in sorted(unique)]

    def write_page(self, instrument, interval, rows):
        if not rows:
            return
        directory = self.directory(instrument, interval)
        directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(encode(rows).encode()).hexdigest()
        destination = directory / f"{digest}.parquet"
        descriptor, name = tempfile.mkstemp(suffix=".tmp", dir=directory)
        os.close(descriptor)
        temporary = Path(name)
        try:
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), temporary)
            with temporary.open("rb") as file:
                os.fsync(file.fileno())
            os.replace(temporary, destination)
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def checkpoint(self, download_id):
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM downloads WHERE id = ?", (download_id,)
            ).fetchone()
        return dict(row) if row else None

    def save_checkpoint(self, key, instrument, interval, start, end, cursor, state):
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """INSERT INTO downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET cursor=excluded.cursor, state=excluded.state,
                updated_at=excluded.updated_at""",
                (
                    key,
                    instrument,
                    interval,
                    start,
                    end,
                    cursor,
                    state,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def save_instrument(self, instrument, snapshot):
        value = encode(snapshot)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO instrument_snapshots VALUES (?, ?, ?)",
                (hashlib.sha256(value.encode()).hexdigest(), instrument, value),
            )

    def quality(self, instrument, interval, start, end):
        begin, finish, step = validate_range(instrument, interval, start, end)
        rows = [row for row in self.rows(instrument, interval) if start <= row["timestamp"] < end]
        actual = {milliseconds(row["timestamp"]) for row in rows}
        missing = []
        missing_count = 0
        run_start = None
        for ts in range(begin, finish, step):
            if ts not in actual:
                missing_count += 1
                if run_start is None:
                    run_start = ts
            elif run_start is not None:
                missing.append([run_start, ts])
                run_start = None
        if run_start is not None:
            missing.append([run_start, finish])
        return {
            "instrument": instrument,
            "interval": interval,
            "source": SOURCE,
            "schema_version": SCHEMA_VERSION,
            "requested_start": str(start),
            "requested_end_exclusive": str(end),
            "rows": len(rows),
            "expected_rows": (finish - begin) // step,
            "missing_count": missing_count,
            "missing_ranges_ms_half_open": missing,
            "complete": missing_count == 0,
            "first_timestamp": str(rows[0]["timestamp"]) if rows else None,
            "last_timestamp": str(rows[-1]["timestamp"]) if rows else None,
            "data_hash": hashlib.sha256(encode(rows).encode()).hexdigest(),
            "availability_notice": (
                "available_at 为实际采集时刻；无法还原历史发布时间，禁止默认为当时已知"
            ),
        }


def validate_range(instrument, interval, start, end):
    if instrument not in INSTRUMENTS or interval not in INTERVALS:
        raise DataError("不支持的标的或周期")
    begin, finish = milliseconds(start), milliseconds(end)
    step = int(INTERVALS[interval].total_seconds() * 1000)
    if finish <= begin or begin % step or finish % step:
        raise DataError("请求须为非空且对齐 UTC 周期的 [start, end) 区间")
    if finish - begin > 3660 * 86400 * 1000:
        raise DataError("单次范围不得超过约十年")
    if end > datetime.now(UTC):
        raise DataError("不允许请求尚未结束的未来区间")
    return begin, finish, step


def sync_history(
    warehouse: Warehouse,
    client: PublicClient,
    instrument: str,
    interval: str,
    start: datetime,
    end: datetime,
    *,
    max_pages=100,
    refresh=False,
):
    begin, finish, _ = validate_range(instrument, interval, start, end)
    if type(max_pages) is not int or not 1 <= max_pages <= 10000:
        raise DataError("单次页数须在 1 到 10000 之间")
    key = hashlib.sha256(encode([instrument, interval, begin, finish]).encode()).hexdigest()
    with warehouse.lock(instrument, interval):
        checkpoint = warehouse.checkpoint(key)
        cursor = checkpoint["cursor"] if checkpoint and not refresh else finish
        state = checkpoint["state"] if checkpoint and not refresh else "partial"
        pages = 0
        if state == "partial":
            warehouse.save_instrument(instrument, client.instrument(instrument))
            known = {row["timestamp"]: row for row in warehouse.rows(instrument, interval)}
            for _ in range(max_pages):
                raw = client.history(instrument, interval, cursor)
                observed = datetime.now(UTC)
                rows, timestamps = parse_page(raw, interval, observed)
                pages += 1
                if timestamps and max(timestamps) > cursor:
                    raise DataError("OKX 页面返回游标之后的数据，拒绝错误分页")
                oldest = min(timestamps) if timestamps else cursor
                if timestamps and oldest >= cursor:
                    raise DataError("分页游标没有前进，保留上一次断点")
                selected = [row for row in rows if start <= row["timestamp"] < end]
                novel = []
                for row in selected:
                    previous = known.get(row["timestamp"])
                    if previous:
                        if any(previous[key] != row[key] for key in PRICE_FIELDS):
                            raise DataError("已封存页面存在冲突行情，拒绝覆盖")
                    else:
                        novel.append(row)
                        known[row["timestamp"]] = row
                warehouse.write_page(instrument, interval, novel)
                # 页数据先原子落盘，再推进断点；中断重放由内容去重处理。
                cursor = oldest
                state = (
                    "exhausted"
                    if not timestamps
                    else ("finished" if cursor <= begin else "partial")
                )
                warehouse.save_checkpoint(key, instrument, interval, begin, finish, cursor, state)
                if state != "partial":
                    break
        return warehouse.quality(instrument, interval, start, end) | {
            "download_id": key,
            "download_state": state,
            "pages_this_run": pages,
            "requests_this_client": client.requests,
        }
