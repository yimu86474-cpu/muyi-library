"""PostgreSQL connection and named rows for the standalone database."""

import psycopg
from psycopg.rows import dict_row


def connect(dsn=None):
    if not dsn:
        raise ValueError("请指定本机独立 PostgreSQL 连接")
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
