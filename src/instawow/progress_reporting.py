from __future__ import annotations

import asyncio
import contextvars
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import partial
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


class _GenericProgress(Progress[Literal['generic']]):
    pass


class _DownloadProgress(Progress[Literal['download'], Literal['bytes']]):
    pass


make_generic_progress = partial(_GenericProgress, type_='generic', current=0, total=0)
make_download_progress = partial(
    _DownloadProgress, type_='download', unit='bytes', current=0, total=0
)


_TProgress = TypeVar('_TProgress', bound=Progress[Any, Any], default=Never)
ReadOnlyProgressGroup: TypeAlias = Mapping[int, _DownloadProgress | _GenericProgress | _TProgress]

_progress_notifiers_var = contextvars.ContextVar[
    frozenset[Callable[[int, Progress[Any, Any] | Literal['unset']], None]]
]('_progress_notifiers_var', default=frozenset())

_progress_id_gen = count()


def get_next_progress_id() -> int:
    return next(_progress_id_gen)


class make_progress_receiver(Generic[_TProgress]):
    "Observe progress within the current context."

    @contextmanager
    def __new__(
        cls,
    ) -> Iterator[
        tuple[
            Callable[[], ReadOnlyProgressGroup[_TProgress]],
            Callable[[], AsyncGenerator[ReadOnlyProgressGroup[_TProgress]]],
        ]
    ]:
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

        _progress_notifiers_var.set(_progress_notifiers_var.get() | {waken})

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
            _progress_notifiers_var.set(_progress_notifiers_var.get() - {waken})


def update_progress(progress_id: int, progress: Progress[Any, Any] | Literal['unset']) -> None:
    "Trigger a manual progress update."
    for notify in _progress_notifiers_var.get():
        notify(progress_id, progress)


def make_incrementing_progress_tracker(
    total: int, label: str
) -> Callable[[Awaitable[_T]], Awaitable[_T]]:
    "Track the progress a finite-length collection of awaitables."
    if total < 1:

        def track_ident(awaitable: Awaitable[_T]):
            return awaitable

        return track_ident

    progress_id = get_next_progress_id()
    progress = make_generic_progress(total=total, label=label)

    def track(awaitable: Awaitable[_T]):
        future = asyncio.ensure_future(awaitable)

        @future.add_done_callback
        def _(task: asyncio.Task[_T]):
            progress['current'] += 1
            update_progress(
                progress_id,
                'unset' if progress['current'] == progress['total'] else progress,
            )

        return future

    update_progress(progress_id, progress)
    return track
