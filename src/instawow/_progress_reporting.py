from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from itertools import count
from typing import Any, Generic, Literal, TypeAlias, cast

from typing_extensions import Never, NotRequired, TypedDict, TypeVar

_T = TypeVar('_T')

_TProgressType = TypeVar('_TProgressType', bound=str)
_TProgressUnit = TypeVar('_TProgressUnit', bound=str | None, default=None)


class Progress(TypedDict, Generic[_TProgressType, _TProgressUnit]):
    type_: _TProgressType
    unit: NotRequired[_TProgressUnit]
    label: NotRequired[str]
    current: int
    total: int


class GenericProgress(Progress[Literal['generic']]):
    pass


class DownloadProgress(Progress[Literal['download'], Literal['bytes']]):
    pass


def make_default_progress(*, type_: Literal['generic', 'download'], label: str, total: int = 0):
    match type_:
        case 'generic':
            return GenericProgress(
                type_='generic',
                label=label,
                current=0,
                total=total,
            )
        case 'download':
            return DownloadProgress(
                type_='download',
                unit='bytes',
                label=label,
                current=0,
                total=total,
            )


_TProgress = TypeVar('_TProgress', bound=Progress[Any, Any], default=Never)
ReadOnlyProgressGroup: TypeAlias = Mapping[int, DownloadProgress | GenericProgress | _TProgress]

progress_notifiers = contextvars.ContextVar(
    'progress_notifiers',
    default=set[Callable[[int, Progress[Any, Any] | Literal['unset']], None]](),
)

_progress_id_gen = count()


def get_next_progress_id() -> int:
    return next(_progress_id_gen)


class make_progress_receiver(Generic[_TProgress]):
    @contextmanager
    def __new__(cls):
        asyncio.get_running_loop()  # Raise if constructed outside async context.

        emit_event = asyncio.Event()

        progress_group: dict[int, Progress[Any, Any]] = {}

        def waken(progress_id: int, progress: Progress[Any, Any] | Literal['unset']):
            if progress == 'unset':
                try:
                    del progress_group[progress_id]
                except KeyError:
                    pass
            else:
                progress_group[progress_id] = progress

            emit_event.set()

        progress_notifiers.set(progress_notifiers.get() | {waken})

        try:

            async def receive():
                while True:
                    await emit_event.wait()
                    yield cast(ReadOnlyProgressGroup[_TProgress], progress_group)
                    emit_event.clear()

            yield receive()

        finally:
            progress_notifiers.set(progress_notifiers.get() - {waken})


def update_progress(progress_id: int, progress: Progress[Any, Any] | Literal['unset']) -> None:
    for notify in progress_notifiers.get():
        notify(progress_id, progress)


def make_incrementing_progress_tracker(total: int, label: str):
    progress_id = get_next_progress_id()
    progress = make_default_progress(type_='generic', total=total, label=label)

    def do_update_progress():
        update_progress(
            progress_id,
            (
                'unset'
                if progress['total'] == 0 or progress['current'] == progress['total']
                else progress
            ),
        )

    def on_done(_task: asyncio.Task[object]):
        progress['current'] += 1
        do_update_progress()

    def track(awaitable: Awaitable[_T]) -> Awaitable[_T]:
        future = asyncio.ensure_future(awaitable)
        future.add_done_callback(on_done)
        return future

    do_update_progress()
    return track
