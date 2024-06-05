import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import sys
import argparse

from .rfr_model.rfr_new import RFR as RFR
# from .softsplat import ModuleSoftsplat as ForwardWarp
from .forward_warp2 import ForwardWarp
from .GridNet import GridNet
from .models.DiffimeInterp_no_cupy import DiffimeInterpNoCupy

from PIL import Image
from torchvision import transforms as TF
from diffusers import ControlNetModel, AutoPipelineForText2Image, AutoPipelineForImage2Image

import cv2


def _tensor_to_canny(tensor):
    """
      Converts a PyTorch tensor of a batch of images to cv2 Canny edge images while maintaining the batch structure.

      Args:
          tensor: A PyTorch tensor of shape (B, C, H, W) representing a batch of images.

      Returns:
          A PyTorch tensor of shape (B, C, H, W) containing the Canny edge images for each input image.
      """
    # Move tensor to CPU if on GPU
    if tensor.device.type == "cuda":
        tensor = tensor.cpu()

    # Create an empty tensor to store Canny edge images
    canny_images = torch.empty_like(tensor)

    # Loop through each image in the batch and apply Canny edge detection
    for i in range(tensor.shape[0]):
        image_tensor = tensor[i]
        canny_image = _process_single_image(image_tensor)
        canny_images[i] = torch.from_numpy(canny_image)  # Convert NumPy array to PyTorch tensor

    return canny_images

def _process_single_image(image_tensor, canny_th_low=50, canny_th_high=150):
    # Convert tensor to numpy array and swap color channels (CHW -> HWC)
    np_img = image_tensor.permute(1, 2, 0).numpy()


    # Handle possible normalization if the tensor values are between 0 and 1
    if np_img.dtype == np.float32:
        np_img *= 255.0

    # Convert to uint8 for cv2 compatibility
    np_img = np_img.astype(np.uint8)

    np_grayscale = cv2.cvtColor(np_img, cv2.COLOR_BGR2GRAY)

    return cv2.Canny(np_grayscale, canny_th_low, canny_th_high)


class CannyDiffimeInterpNoCupy(DiffimeInterpNoCupy):
    """The quadratic model"""
    def __init__(self, path='models/raft_model/models/rfr_sintel_latest.pth-no-zip', config=None,  canny_th_low=50, canny_th_high=150):
        super(CannyDiffimeInterpNoCupy, self).__init__()


        self.cth_low = canny_th_low
        self.cth_high = canny_th_high
        print("loading controlnet")
        controlnet = ControlNetModel.from_pretrained(
            config.controlnet_id,
            torch_dtype=torch.float16,
            variant="fp16",
            use_safetensors=True,
        )
        print("controlnet loaded")
        self.load_diffuser()
        print("loading adapter")
        self.pipeline.load_adapter(config.ip_adapter_id)
        self.pipline.set_ip_adapter_scale(0.9)
        print("adapter loaded")

        self.store_path = config.store_path
        self.counter = 0

        if path is not None:
            dict1 = torch.load(path)
            dict2 = dict()
            for key in dict1:
                dict2[key[7:]] = dict1[key]
            self.flownet.load_state_dict(dict2, strict=False)

    def dflow(self, flo, target):
        tmp = F.interpolate(flo, target.size()[2:4])
        tmp[:, :1] = tmp[:, :1].clone() * tmp.size()[3] / flo.size()[3]
        tmp[:, 1:] = tmp[:, 1:].clone() * tmp.size()[2] / flo.size()[2]

        return tmp


    def motion_calculation(self, Is, Ie, Flow, features, t, ind):
        """
        Args:
            Is: source image
            Ie: target image
            Flow: initial flow

            t: interpolation factor
            ind: index of the frame
        """
        F12, F12in, _ = self.flownet(Is, Ie, iters=12, test_mode=False, flow_init=Flow)
        if ind == 0:
            Ft = t * F12
        else:
            Ft = (1-t) * F12

        Ftd = self.dflow(Ft, features[0])
        Ftdd = self.dflow(Ft, features[1])
        Ftddd = self.dflow(Ft, features[2])

        return F12, F12in, Ft, Ftd, Ftdd, Ftddd


    def forward(self, I1, I2, F12i, F21i, t):
        I1o = (I1 - 0.5) / 0.5
        I2o = (I2 - 0.5) / 0.5

        # extract features

        features1 = self.feat_ext(I1o)
        feat11, feat12, feat13 = features1
        features2 = self.feat_ext(I2o)
        feat21, feat22, feat23 = features2

        # calculate motion

        F12, F12in, F1t, F1td, F1tdd, F1tddd = self.motion_calculation(I1o, I2o, F12i, features1, t, 0)
        F21, F21in, F2t, F2td, F2tdd, F2tddd = self.motion_calculation(I2o, I1o, F21i, features2, t, 1)

        # canny edge
        I1c = _tensor_to_canny(I1)
        I2c = _tensor_to_canny(I2)

        # warping
        w_I1c, _ = self.fwarp(I1c, F1t)
        w_I2c, _ = self.fwarp(I2c, F2t)

        w_I1c_img = self.revtrans(w_I1c.cpu()[0])
        w_I2c_img = self.revtrans(w_I2c.cpu()[0])

        print("canny created")

        # diffuser
        diffused_I1c = self.pipline("", image=w_I1c_img, ip_adapter_image=I1)
        diffused_I2c = self.pipline("", image=w_I2c_img, ip_adapter_image=I2)

        print("diffused")

        # for exploration and understanding the model, saves the intermediate results
        # self.revtrans(w_I1c.cpu()[0]).save(f'{self.store_path}/canny_I1_{self.counter}.png')
        # self.revtrans(w_I2c.cpu()[0]).save(f'{self.store_path}/canny_I2_{self.counter}.png')
        diffused_I1c.save(f'{self.store_path}/cDiff_I1_{self.counter}.png')
        diffused_I2c.save(f'{self.store_path}/cDiff_I2_{self.counter}.png')
        self.counter += 1


        # I1t, norm1 = self.fwarp(I1, F1t)
        # dI1t, dNorm1 = self.fwarp(diffused_I1c, F1t)
        feat1t1, norm1t1 = self.fwarp(feat11, F1td)
        feat1t2, norm1t2 = self.fwarp(feat12, F1tdd)
        feat1t3, norm1t3 = self.fwarp(feat13, F1tddd)

        # I2t, norm2 = self.fwarp(I2, F2t)
        # dI2t, dNorm2 = self.fwarp(diffused_I2c, F2t)
        feat2t1, norm2t1 = self.fwarp(feat21, F2td)
        feat2t2, norm2t2 = self.fwarp(feat22, F2tdd)
        feat2t3, norm2t3 = self.fwarp(feat23, F2tddd)

        # normalize
        # Note: normalize in this way benefit training than the original "linear"
        # I1t[norm1 > 0] = I1t.clone()[norm1 > 0] / norm1[norm1 > 0]
        # I2t[norm2 > 0] = I2t.clone()[norm2 > 0] / norm2[norm2 > 0]
        # self.revtrans(I1c.cpu()[0]).save(f'{self.store_path}/I1t_{self.counter}.png')
        # self.revtrans(I2c.cpu()[0]).save(f'{self.store_path}/I2t_{self.counter}.png')
        # dI1t[dNorm1 > 0] = dI1t.clone()[dNorm1 > 0] / dNorm1[dNorm1 > 0]
        # dI2t[dNorm2 > 0] = dI2t.clone()[dNorm2 > 0] / dNorm2[dNorm2 > 0]

        feat1t1[norm1t1 > 0] = feat1t1.clone()[norm1t1 > 0] / norm1t1[norm1t1 > 0]
        feat2t1[norm2t1 > 0] = feat2t1.clone()[norm2t1 > 0] / norm2t1[norm2t1 > 0]

        feat1t2[norm1t2 > 0] = feat1t2.clone()[norm1t2 > 0] / norm1t2[norm1t2 > 0]
        feat2t2[norm2t2 > 0] = feat2t2.clone()[norm2t2 > 0] / norm2t2[norm2t2 > 0]

        feat1t3[norm1t3 > 0] = feat1t3.clone()[norm1t3 > 0] / norm1t3[norm1t3 > 0]
        feat2t3[norm2t3 > 0] = feat2t3.clone()[norm2t3 > 0] / norm2t3[norm2t3 > 0]

        # synthesis
        It_warp = self.synnet(torch.cat([diffused_I1c, diffused_I2c], dim=1), torch.cat([feat1t1, feat2t1], dim=1),
                              torch.cat([feat1t2, feat2t2], dim=1), torch.cat([feat1t3, feat2t3], dim=1))
        #
        # warp_im = TF.ToPILImage(revNormalize(It_warp.cpu()[0]).clamp(0.0, 1.0))

        return It_warp, F12, F21, F12in, F21in