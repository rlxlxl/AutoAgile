from dataclasses import dataclass


@dataclass
class YouGileItem:
    id: str
    title: str


@dataclass
class MonitorConfig:
    column_id: str
    project_id: str = ""
    board_id: str = ""
    poll_interval: int = 10
