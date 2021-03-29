import json

import torch.nn as nn

from args import get_parser
from mtad_gat import MTAD_GAT
from prediction import Predictor
from training import Trainer
from utils import *

if __name__ == "__main__":

    parser = get_parser()
    args = parser.parse_args()

    if args.dataset == "SMD":
        output_path = f"output/SMD/{args.group}"
    else:
        output_path = f"output/{args.dataset}"

    log_dir = f"{output_path}/logs"

    if not os.path.exists(output_path):
        os.makedirs(output_path)

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    if not os.path.exists(args.model_path):
        os.makedirs(args.model_path)

    dataset = args.dataset
    do_preprocess = args.do_preprocess
    window_size = args.lookback
    horizon = args.horizon
    n_epochs = args.epochs
    batch_size = args.bs
    init_lr = args.init_lr
    val_split = args.val_split
    shuffle_dataset = args.shuffle_dataset
    use_cuda = args.use_cuda
    model_path = args.model_path
    print_every = args.print_every
    group_index = args.group[0]
    index = args.group[2:]
    args_summary = str(args.__dict__)
    print(args_summary)

    if args.dataset == "SMD":
        (x_train, _), (x_test, y_test) = get_data(f"machine-{group_index}-{index}", do_preprocess=do_preprocess)
    else:
        (x_train, _), (x_test, y_test) = get_data(dataset, do_preprocess=do_preprocess)

    x_train = torch.from_numpy(x_train).float()
    x_test = torch.from_numpy(x_test).float()
    n_features = x_train.shape[1]

    target_dims = get_target_dims(dataset)
    if target_dims is None:
        out_dim = n_features
    elif type(target_dims) == int:
        out_dim = 1
    else:
        out_dim = len(target_dims)

    train_dataset = SlidingWindowDataset(x_train, window_size, target_dims)
    test_dataset = SlidingWindowDataset(x_test, window_size, target_dims)

    train_loader, val_loader, test_loader = create_data_loaders(
        train_dataset, batch_size, val_split, shuffle_dataset, test_dataset=test_dataset
    )

    model = MTAD_GAT(
        n_features,
        window_size,
        horizon,
        out_dim,
        batch_size,
        kernel_size=args.kernel_size,
        dropout=args.dropout,
        gru_n_layers=args.gru_layers,
        gru_hid_dim=args.gru_hid_dim,
        autoenc_n_layers=args.autoenc_layers,
        autoenc_hid_dim=args.autoenc_hid_dim,
        forecast_n_layers=args.fc_layers,
        forecast_hid_dim=args.fc_hid_dim,
        use_cuda=args.use_cuda,
    )

    optimizer = torch.optim.Adam(model.parameters(), lr=args.init_lr)
    forecast_criterion = nn.MSELoss()
    recon_criterion = nn.MSELoss()

    trainer = Trainer(
        model,
        optimizer,
        window_size,
        n_features,
        target_dims,
        n_epochs,
        batch_size,
        init_lr,
        forecast_criterion,
        recon_criterion,
        use_cuda,
        model_path,
        log_dir,
        print_every,
        args_summary,
    )

    trainer.fit(train_loader, val_loader)

    plot_losses(trainer.losses, save_path=output_path)

    # Check test loss
    test_loss = trainer.evaluate(test_loader)
    print(f"Test forecast loss: {test_loss[0]:.5f}")
    print(f"Test reconstruction loss: {test_loss[1]:.5f}")
    print(f"Test total loss: {test_loss[2]:.5f}")

    # Predict anomalies
    # 'level' argument for POT-method
    if args.level is not None:
        level = args.level
    level_dict = {
        "SMAP": 0.93,
        "MSL": 0.99,
        "SMD-1": 0.9950,
        "SMD-2": 0.9925,
        "SMD-3": 0.9999,
        'TELENOR': 0.99
    }
    key = "SMD-" + args.group[0] if args.dataset == "SMD" else args.dataset
    level = level_dict[key]

    trainer.load(f"{model_path}/{trainer.id}/{trainer.id}_model.pt")
    prediction_args = {
        'model_name': trainer.id,
        'target_dims': target_dims,
        'level': level,
        'q': args.q,
        'use_mov_av': args.use_mov_av,
        'gamma': args.gamma,
        'save_path': output_path
    }
    best_model = trainer.model
    predictor = Predictor(
        best_model,
        window_size,
        n_features,
        prediction_args,
    )
    if y_test is not None:
        label = y_test[window_size:]
    predictor.predict_anomalies(x_train, x_test, label, save_scores=True)

    # Save config
    args_path = f"{model_path}/{trainer.id}/{trainer.id}_config.txt"
    with open(args_path, "w") as f:
        json.dump(args.__dict__, f, indent=2)
