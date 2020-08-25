#
# Copyright (c) 2020, Neptune Labs Sp. z o.o.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from threading import Event
from time import time

from neptune.internal.containers.storage_queue import StorageQueue
from neptune.internal.neptune_backend import NeptuneBackend
from neptune.internal.operation import Operation, VersionedOperation
from neptune.internal.operation_processor import OperationProcessor
from neptune.internal.threading.daemon import Daemon

# pylint: disable=protected-access


class AsyncOperationProcessor(OperationProcessor):

    def __init__(self,
                 queue: StorageQueue[VersionedOperation],
                 backend: NeptuneBackend,
                 sleep_time: float = 5,
                 batch_size: int = 1000):
        self._queue = queue
        self._backend = backend
        self._last_version = 0
        self._consumed_version = 0
        self._waiting_for_version = 0
        self._waiting_event = Event()
        self._consumer = self.ConsumerThread(self, sleep_time, batch_size)
        self._consumer.start()

    def enqueue_operation(self, op: Operation, wait: bool) -> None:
        self._last_version += 1
        self._queue.put(VersionedOperation(op, self._last_version))
        if self._queue.is_overflowing():
            self._consumer.wake_up()
        if wait:
            self.wait()

    def wait(self):
        self._waiting_for_version = self._last_version
        if self._consumed_version >= self._waiting_for_version:
            self._waiting_for_version = 0
            return
        self._waiting_event.wait()
        self._waiting_event.clear()

    class ConsumerThread(Daemon):

        def __init__(self,
                     processor: 'AsyncOperationProcessor',
                     sleep_time: float,
                     batch_size: int):
            super().__init__(sleep_time=sleep_time)
            self._processor = processor
            self._batch_size = batch_size
            self._last_flush = 0

        def work(self) -> None:
            ts = time()
            if ts - self._last_flush >= self._sleep_time:
                self._last_flush = ts
                self._processor._queue.flush()

            batch = self._processor._queue.get_batch(self._batch_size)
            if not batch:
                return
            self._processor._backend.execute_operations([op.op for op in batch])
            self._processor._consumed_version = batch[-1].version
            if self._processor._waiting_for_version > 0:
                if self._processor._consumed_version >= self._processor._waiting_for_version:
                    self._processor._waiting_for_version = 0
                    self._processor._waiting_event.set()
