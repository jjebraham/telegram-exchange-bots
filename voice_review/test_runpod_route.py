from pathlib import Path
import os,tempfile,unittest
from unittest.mock import patch
import instagram_trial_reels as trial
import instagram_reel_motion as motion
import runpod_reel_render as gpu


class ProductionRouteTests(unittest.TestCase):
    def run_case(self,flag,side_effect=None,fallback='true'):
        root=tempfile.TemporaryDirectory();self.addCleanup(root.cleanup)
        output=Path(root.name)/'video.mp4'
        story={'title_fa':'عنوان خبر','summary_fa':'این یک خبر آزمایشی است.','source_name':'source','reel_length':'long'}
        def local(*args,**kwargs):output.write_bytes(b'v'*100_001)
        def remote(*args,**kwargs):
            if side_effect:raise side_effect
            output.write_bytes(b'v'*100_001);story['_rendering']={'renderer':'runpod'};return 20
        with patch.dict(os.environ,{'REEL_RUNPOD_ENABLED':flag,'REEL_LOCAL_RENDER_FALLBACK':fallback}), \
             patch.object(gpu,'render',side_effect=remote) as gm,patch.object(motion,'render',side_effect=local) as lm, \
             patch.object(trial,'_probe_video',return_value=20):
            try:result=trial.render_video(story,'economy',output,Path(root.name),ffmpeg='ffmpeg',ffprobe='ffprobe')
            except trial.TrialReelError:result='rejected'
            return result,gm.call_count,lm.call_count,story
    def test_disabled_flag_keeps_local_renderer(self):self.assertEqual(self.run_case('false')[:3],(20,0,1))
    def test_verified_gpu_route_skips_duplicate_cpu_render(self):
        result=self.run_case('true');self.assertEqual(result[:3],(20,1,0));self.assertEqual(result[3]['_rendering']['renderer'],'runpod')
    def test_budget_or_confirmed_capacity_failure_falls_back_to_cpu(self):
        self.assertEqual(self.run_case('true',gpu.RenderError('budget',fallback_safe=True))[:3],(20,1,1))
    def test_unknown_gpu_state_blocks_publication_and_unsafe_fallback(self):
        self.assertEqual(self.run_case('true',gpu.RenderError('unconfirmed'))[:3],('rejected',1,0))
    def test_disabled_fallback_is_respected(self):
        self.assertEqual(self.run_case('true',gpu.RenderError('budget',fallback_safe=True),'false')[:3],('rejected',1,0))


if __name__=='__main__':unittest.main()
