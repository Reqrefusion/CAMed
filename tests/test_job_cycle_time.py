import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freecad.camed.program_backend import configure_cycle_time


class NativeJob:
    def __init__(self, obj):
        self.obj = obj
        self.calls = 0

    def getCycleTime(self):
        self.calls += 1
        self.obj.CycleTime = '00:03:14'


class JobCycleTimeTests(unittest.TestCase):
    def setUp(self):
        self.section = SimpleNamespace(
            CAMEditorProgram=object(), ToolController=None, Path=SimpleNamespace(Length=10)
        )
        self.job = SimpleNamespace(CAMEditorSession=True, Operations=SimpleNamespace(Group=[self.section]))
        self.job.Proxy = NativeJob(self.job)
        module = SimpleNamespace(ObjectJob=NativeJob)
        self.modules = patch.dict(sys.modules, {'Path.Main.Job': module})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_missing_section_controller_defers_estimation_until_tools_exist(self):
        configure_cycle_time(self.job)
        configure_cycle_time(self.job)
        for controller in (None, SimpleNamespace(ToolNumber=0)):
            self.section.ToolController = controller
            self.job.Proxy.getCycleTime()
            self.assertEqual(self.job.CycleTime, '—')
            self.assertEqual(self.job.Proxy.calls, 0)
        self.section.ToolController = SimpleNamespace(ToolNumber=4)
        self.job.Proxy.getCycleTime()
        self.assertEqual(self.job.CycleTime, '00:03:14')
        self.assertEqual(self.job.Proxy.calls, 1)

    def test_empty_path_and_non_editor_operations_retain_native_estimation(self):
        configure_cycle_time(self.job)
        self.section.Path.Length = 0
        self.job.Proxy.getCycleTime()
        self.section.Path.Length = 10
        self.section.CAMEditorProgram = None
        self.job.Proxy.getCycleTime()
        self.assertEqual(self.job.Proxy.calls, 2)

    def test_other_jobs_keep_their_native_proxy_method(self):
        self.job.CAMEditorSession = False
        configure_cycle_time(self.job)
        self.assertNotIn('getCycleTime', vars(self.job.Proxy))
