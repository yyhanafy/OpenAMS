from pathlib import Path
import numpy as np
from openams.technology.ml_surrogate.dataset import MosDataset, MosDatasetSplit
from openams.technology.ml_surrogate.model import MosMlpConfig
from openams.technology.ml_surrogate.predictor import MosMlpBundle
from openams.technology.ml_surrogate.trainer import TrainingConfig, save_checkpoint, train_model


def test_checkpoint_forward_and_inverse_roundtrip(tmp_path):
    widths = np.linspace(1, 10, 80)
    vgs = np.linspace(.5, 1.2, 80)
    features = np.column_stack((np.log(widths), np.zeros(80)+np.log(.5), vgs, np.ones(80), np.zeros(80)))
    current = 1e-6 * widths * np.exp(3*vgs)
    targets = np.column_stack((np.log(current), np.log(current*5), np.log(current*.1),
                               np.zeros(80)+.2, np.zeros(80)+.5))
    ds = MosDataset("nmos", features, targets, np.ones(80,bool), tuple(map(str,range(80))), {})
    split = MosDatasetSplit(ds, ds, ds)
    result = train_model(split, model_config=MosMlpConfig(hidden_dims=(32,32)),
        training_config=TrainingConfig(epochs=600, batch_size=80, learning_rate=4e-3, patience=120, seed=3))
    path = tmp_path / "nmos.pt"
    domain = {"width_um":[1,10], "length_um":[.5,.5], "vgs_abs_v":[.5,1.2],
              "vds_abs_v":[1,1], "vbs_abs_v":[0,0]}
    save_checkpoint(path, result=result, polarity="nmos", domain=domain, metadata={})
    bundle = MosMlpBundle.load({"nmos": path})
    pred = bundle.predict(polarity="nmos", width_um=5, length_um=.5, vgs_abs_v=.8, vds_abs_v=1, vbs_abs_v=0)
    solved_w = bundle.solve_width(polarity="nmos", target_current_a=pred.id_abs_a, length_um=.5,
                                  vgs_abs_v=.8, vds_abs_v=1, vbs_abs_v=0)
    solved_v = bundle.solve_vgs(polarity="nmos", target_current_a=pred.id_abs_a, width_um=5,
                                length_um=.5, vds_abs_v=1, vbs_abs_v=0)
    assert abs(solved_w.value-5) < .1
    assert abs(solved_v.value-.8) < .02
