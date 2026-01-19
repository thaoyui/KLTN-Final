"""
Ansible Callback Plugin để đo timing chi tiết từng task
"""
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import time
from ansible.plugins.callback import CallbackBase

class CallbackModule(CallbackBase):
    """
    Callback plugin để đo timing chi tiết từng task
    """
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'timing_callback'
    CALLBACK_NEEDS_WHITELIST = False

    def __init__(self):
        super(CallbackModule, self).__init__()
        self.task_timings = {}
        self.current_task = None
        self.current_task_start = None

    def v2_playbook_on_task_start(self, task, is_conditional):
        """Ghi lại thời gian bắt đầu task"""
        self.current_task = task.get_name()
        self.current_task_start = time.time()
        if self.current_task not in self.task_timings:
            self.task_timings[self.current_task] = []

    def v2_runner_on_ok(self, result):
        """Ghi lại thời gian khi task thành công"""
        if self.current_task and self.current_task_start:
            duration = time.time() - self.current_task_start
            self.task_timings[self.current_task].append({
                'host': result._host.get_name(),
                'duration': duration,
                'status': 'ok'
            })
        # Hiển thị debug output (cần cho bootstrap status JSON)
        if result._result.get('_ansible_verbose_always') or 'msg' in result._result:
            self._display.display(f"{result._host.get_name()} | SUCCESS => {self._dump_results(result._result, indent=0)}", color='green')

    def v2_runner_on_failed(self, result, ignore_errors=False):
        """Ghi lại thời gian khi task failed"""
        if self.current_task and self.current_task_start:
            duration = time.time() - self.current_task_start
            self.task_timings[self.current_task].append({
                'host': result._host.get_name(),
                'duration': duration,
                'status': 'failed'
            })

    def v2_playbook_on_stats(self, stats):
        """Hiển thị timing summary khi playbook kết thúc"""
        self._display.display("\n=== TASK TIMING BREAKDOWN ===")
        for task_name, timings in self.task_timings.items():
            if timings:
                total_duration = sum(t['duration'] for t in timings)
                avg_duration = total_duration / len(timings)
                self._display.display(
                    f"Task: {task_name[:50]}... | "
                    f"Total: {total_duration:.3f}s | "
                    f"Avg: {avg_duration:.3f}s | "
                    f"Count: {len(timings)}"
                )

