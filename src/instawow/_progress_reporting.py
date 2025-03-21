from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from itertools import count
from typing import Any, Generic, Literal, LiteralString, Never, NotRequired, TypeAlias

from typing_extensions import TypedDict, TypeVar

_T = TypeVar('_T')

_TProgressType = TypeVar('_TProgressType', bound=LiteralString)
_TProgressUnit = TypeVar('_TProgressUnit', bound=LiteralString | None, default=None)


class Progress(TypedDict, Generic[_TProgressType, _TProgressUnit]):
    type_: _TProgressType
    unit: NotRequired[_TProgressUnit]
    label: NotRequired[str]
    current: int
    total: int | None


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

progress_notifiers = contextvars.ContextVar[
    frozenset[Callable[[int, Progress[Any, Any] | Literal['unset']], None]]
]('progress_notifiers', default=frozenset())

_progress_id_gen = count()


def get_next_progress_id() -> int:
    return next(_progress_id_gen)


class make_progress_receiver(Generic[_TProgress]):
    @contextmanager
    def __new__(cls):
        asyncio.get_running_loop()  # Raise if constructed outside async context.

        emit_event = asyncio.Event()

        progress_group: ReadOnlyProgressGroup[_TProgress] = {}

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

            def get_once():
                return progress_group

            async def make_iter():
                while True:
                    await emit_event.wait()
                    yield progress_group
                    emit_event.clear()

            yield (get_once, make_iter)

        finally:
            progress_notifiers.set(progress_notifiers.get() - {waken})


def update_progress(progress_id: int, progress: Progress[Any, Any] | Literal['unset']) -> None:
    for notify in progress_notifiers.get():
        notify(progress_id, progress)


def make_incrementing_progress_tracker(total: int, label: str):
    if total < 1:

        def track_ident(awaitable: Awaitable[_T]) -> Awaitable[_T]:
            return awaitable

        return track_ident

    progress_id = get_next_progress_id()
    progress = make_default_progress(type_='generic', total=total, label=label)

    def on_done(_task: asyncio.Task[object]):
        progress['current'] += 1
        update_progress(
            progress_id,
            'unset' if progress['current'] == progress['total'] else progress,
        )

    def track(awaitable: Awaitable[_T]) -> Awaitable[_T]:
        future = asyncio.ensure_future(awaitable)
        future.add_done_callback(on_done)
        return future

    update_progress(progress_id, progress)
    return track
