参考文章：[GAN 原理 & pytorch代码实例 - 生成MINIST手写数字](https://blog.csdn.net/Lizhi_Tech/article/details/132108893)


GAN 的训练结果很难通过损失直接体现出来，通过观察保存在`data`目录的中间结果来判断训练效果。

`digit_generate`利用手写数字识别的模型来帮助生成质量更高的数字图片，但是效果似乎没有很好？