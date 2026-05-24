from dataclasses import dataclass, field
from typing import List


@dataclass
class EventLog:
    entries: List[str] = field(default_factory=list)

    def add(self, tag: str, message: str):
        line = f"[{tag}] {message}"
        self.entries.append(line)
        print(line)

    def clear(self):
        self.entries.clear()

    def text(self):
        result = "\n".join(self.entries)
        return result