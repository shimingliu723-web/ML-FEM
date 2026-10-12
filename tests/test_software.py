import sys,json,unittest,math,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from software_service import BUILTINS,catalog,validate_basic,VECTORS
from target_manager import get_target
from code_audit import locate_code
from repair_manager import _memcmp_block,_classify_memcmp
from vector_validation import validate_vectors
from stats import paired_block_analysis,student_t_critical

class SoftwareRegression(unittest.TestCase):
    def test_seven_builtins(self):
        self.assertEqual(len(BUILTINS),7)
        self.assertTrue(set(BUILTINS)<=set(t['id'] for t in catalog()))
    def test_path_rejected(self):
        with self.assertRaises(ValueError):get_target('../backend')
    def test_all_compare_patterns(self):
        for target in BUILTINS:
            expected='early_return' if target.startswith('variant_early_return') else 'fixed_time'
            self.assertEqual(locate_code(target)['compare_style'],expected,target)
    def test_function_extraction_ignores_comment_braces(self):
        source='static MLK_INLINE uint8_t mlk_ct_memcmp(int a) { /* } */ if(a) { return 0xFF; } return 0; }\nint other;'
        a,b,block=_memcmp_block(source)
        self.assertNotIn('other',block);self.assertEqual(source[b:].strip(),'int other;')
        self.assertEqual(_classify_memcmp(block),'early_return_compare')
    def test_missing_expected_not_a_pass(self):
        item=json.loads(VECTORS.read_text())[0]
        item.pop('ss',None);item.pop('shared_secret',None)
        r=validate_vectors(json.dumps(item))
        self.assertEqual(r['passed'],0);self.assertFalse(r['success'])
        for forbidden in ['secret_key_sha256','actual_shared_secret','expected_shared_secret']:
            self.assertNotIn(forbidden,json.dumps(r))
    def test_corrupted_expected_fails(self):
        import base64
        item=json.loads(VECTORS.read_text())[0];item['ss']=base64.b64encode(bytes(32)).decode()
        self.assertFalse(validate_vectors(json.dumps(item))['success'])
    def test_ci_uses_t_for_five_blocks(self):
        a=[10000]*1000;b=[10000+(i//200)*2+1 for i in range(1000)];order=[i%2 for i in range(1000)]
        r=paired_block_analysis(a,b,order);lo,hi=r['paired_difference_ci_ns']
        self.assertAlmostEqual((hi-lo)/2/r['paired_standard_error_ns'],student_t_critical(4),places=8)
    def test_full_vectors_selected_target(self):
        from software_vectors import validate_official
        result=validate_official('variant_early_return_xor',['512','768','1024'])
        self.assertEqual(result['total'],435)
        self.assertTrue(result['success'])
        self.assertEqual({r['operation'] for r in result['results']},{'keyGeneration','encapsulation','decapsulation','encapsulationKeyCheck','decapsulationKeyCheck'})
if __name__=='__main__':unittest.main()
