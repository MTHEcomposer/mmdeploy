import h5py
import numpy as np
import tensorrt as trt
import torch

DEFAULT_CALIBRATION_ALGORITHM = trt.CalibrationAlgoType.ENTROPY_CALIBRATION_2


class HDF5Calibrator(trt.IInt8Calibrator):

    def __init__(self,
                 calib_file,
                 opt_shape_dict,
                 model_type='end2end',
                 device_id=0,
                 algorithm=DEFAULT_CALIBRATION_ALGORITHM,
                 **kwargs):
        super().__init__()

        if isinstance(calib_file, str):
            calib_file = h5py.File(calib_file, mode='r')

        assert 'calib_data' in calib_file
        calib_data = calib_file['calib_data']
        assert model_type in calib_data
        calib_data = calib_data[model_type]

        self.calib_file = calib_file
        self.calib_data = calib_data
        self.device_id = device_id
        self.algorithm = algorithm
        self.opt_shape_dict = opt_shape_dict
        self.kwargs = kwargs

        # create buffers that will hold data batches
        self.buffers = dict()

        self.count = 0
        first_input_group = calib_data[list(calib_data.keys())[0]]
        self.dataset_length = len(first_input_group)
        self.batch_size = first_input_group['0'].shape[0]

    def __del__(self):

        if hasattr(self, 'calib_file'):
            self.calib_file.close()

    def get_batch(self, names, **kwargs):
        if self.count < self.dataset_length:

            ret = []
            for name in names:
                input_group = self.calib_data[name]
                data_np = input_group[str(self.count)][...]
                data_torch = torch.from_numpy(data_np)

                # tile the tensor so we can keep the same distribute
                opt_shape = self.opt_shape_dict[name]['opt_shape']
                data_shape = data_torch.shape

                reps = [
                    int(np.ceil(opt_s / data_s))
                    for opt_s, data_s in zip(opt_shape, data_shape)
                ]

                data_torch = data_torch.tile(reps)

                for dim, opt_s in enumerate(opt_shape):
                    if data_torch.shape[dim] != opt_s:
                        data_torch = data_torch.narrow(dim, 0, opt_s)

                if name not in self.buffers:
                    self.buffers[name] = data_torch.cuda(self.device_id)
                else:
                    self.buffers[name].copy_(data_torch.cuda(self.device_id))

                ret.append(int(self.buffers[name].data_ptr()))
            self.count += 1
            return ret
        else:
            return None

    def get_algorithm(self):
        return self.algorithm

    def get_batch_size(self):
        return self.batch_size

    def read_calibration_cache(self, *args, **kwargs):
        return None

    def write_calibration_cache(self, cache, *args, **kwargs):
        pass
