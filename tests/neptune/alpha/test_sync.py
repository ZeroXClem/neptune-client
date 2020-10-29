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

# pylint: disable=redefined-outer-name

import uuid
from random import randint

import neptune.alpha.sync
from neptune.alpha.constants import OPERATIONS_DISK_QUEUE_PREFIX
from neptune.alpha.internal.containers.disk_queue import DiskQueue
from neptune.alpha.internal.utils.sync_offset_file import SyncOffsetFile
from neptune.alpha.internal.operation import Operation
from neptune.alpha.sync import partition_experiments, Experiment, get_qualified_name, list_experiments, \
    sync_all_experiments, sync_selected_experiments


def an_experiment():
    return Experiment(str(uuid.uuid4()), 'EXP-{}'.format(randint(42, 142)), 'org', 'proj')


def prepare_experiments(tmp_path):
    unsync_exp = an_experiment()
    sync_exp = an_experiment()
    experiments = (unsync_exp, sync_exp)

    for exp in experiments:
        exp_path = tmp_path / exp.uuid
        exp_path.mkdir()
        queue = DiskQueue(str(exp_path), OPERATIONS_DISK_QUEUE_PREFIX, lambda x: x, lambda x: x)
        queue.put({'version': 0, 'op': 'op-0'})
        queue.put({'version': 1, 'op': 'op-1'})

    sync_offset_file = SyncOffsetFile(tmp_path / unsync_exp.uuid)
    sync_offset_file.write(0)

    sync_offset_file = SyncOffsetFile(tmp_path / sync_exp.uuid)
    sync_offset_file.write(1)

    def get_experiment_impl(experiment_id):
        for exp in experiments:
            if experiment_id in (exp.uuid, get_qualified_name(exp)):
                return exp

    return unsync_exp, sync_exp, get_experiment_impl


def test_list_experiments(tmp_path, mocker, capsys):
    # given
    unsync_exp, sync_exp, get_experiment_impl = prepare_experiments(tmp_path)

    # and
    mocker.patch.object(neptune.alpha.sync, 'get_experiment', get_experiment_impl)
    mocker.patch.object(Operation, 'from_dict')

    # when
    result = partition_experiments(tmp_path)
    list_experiments(tmp_path, *result)

    # then
    assert result[0] == [sync_exp]
    assert result[1] == [unsync_exp]

    # and
    captured = capsys.readouterr()
    assert captured.err == ''
    assert 'Synchronised experiments:\n- {}'.format(get_qualified_name(sync_exp)) in captured.out
    assert 'Unsynchronised experiments:\n- {}'.format(get_qualified_name(unsync_exp)) in captured.out

def test_sync_all_experiments(tmp_path, mocker, capsys):
    # given
    unsync_exp, sync_exp, get_experiment_impl = prepare_experiments(tmp_path)

    # and
    mocker.patch.object(neptune.alpha.sync, 'get_experiment', get_experiment_impl)
    mocker.patch.object(neptune.alpha.sync, 'backend')
    mocker.patch.object(neptune.alpha.sync.backend, 'execute_operations')
    mocker.patch.object(Operation, 'from_dict', lambda x: x)

    # when
    sync_all_experiments(tmp_path)

    # then
    captured = capsys.readouterr()
    assert captured.err == ''
    assert 'Synchronising {}'.format(get_qualified_name(unsync_exp)) in captured.out
    assert 'Synchronization of experiment {} completed.'.format(get_qualified_name(unsync_exp)) in captured.out
    assert 'Synchronising {}'.format(get_qualified_name(sync_exp)) not in captured.out

    # and
    # pylint: disable=no-member
    neptune.alpha.sync.backend.execute_operations.assert_called_once_with(unsync_exp.uuid, ['op-1'])

def test_sync_selected_experiments(tmp_path, mocker, capsys):
    # given
    unsync_exp, sync_exp, get_experiment_impl = prepare_experiments(tmp_path)

    # and
    mocker.patch.object(neptune.alpha.sync, 'get_experiment', get_experiment_impl)
    mocker.patch.object(neptune.alpha.sync, 'backend')
    mocker.patch.object(neptune.alpha.sync.backend, 'execute_operations')
    mocker.patch.object(Operation, 'from_dict', lambda x: x)

    # when
    sync_selected_experiments(tmp_path, [get_qualified_name(sync_exp)])

    # then
    captured = capsys.readouterr()
    assert captured.err == ''
    assert 'Synchronising {}'.format(get_qualified_name(sync_exp)) in captured.out
    assert 'Synchronization of experiment {} completed.'.format(get_qualified_name(sync_exp)) in captured.out
    assert 'Synchronising {}'.format(get_qualified_name(unsync_exp)) not in captured.out

    # and
    # pylint: disable=no-member
    neptune.alpha.sync.backend.execute_operations.assert_not_called()
