# prefix = 'D:/University/ForthYear/GuidedProject/atd_12k/'
# prefix = 'Datasets_root/'
# testset_root = prefix + 'datasets/test_2k_540p'
# test_flow_root = prefix + 'datasets/test_2k_pre_calc_sgm_flows'
# test_annotation_root = prefix + 'datasets/test_2k_annotations/'

# prefix = 'D:/University/ForthYear/GuidedProject/other_animations'
# prefix = 'Datasets_root/other_animations/'
prefix = ''
testset_root = prefix + 'other_animations/full_shots/'
test_flow_root = prefix + 'outputs/AoT_sgm_flows/'

test_size = (960, 540)
test_crop_size = (960, 540)
# test_size = (1920, 1080)
# test_crop_size = (1920, 1080)

mean = [0., 0., 0.]
std = [1, 1, 1]

inter_frames = 1

model = 'DiffimeInterp'
pwc_path = None

checkpoint = 'checkpoints/anime_interp_full.ckpt'
# diff_path = 'checkpoints/diffusers/runwayml/stable-diffusion-v1-5'
diff_path = 'runwayml/stable-diffusion-v1-5'

diff_objective = None

store_path = 'outputs/diffusion_test1'


