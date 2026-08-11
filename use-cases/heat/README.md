### How To RUN HEAT via ROSE aaS

1. We assume you already finshed the [SETUP.md](../SETUP.md) (mandatory for all use cases).

2. Once you have successfully finished setting up the service, you can navigate to the [HEAT](https://heat-flux-engineering-analysis-toolkit-heat.readthedocs.io/en/latest/TUItutorial.html#running-an-bind-mounted-heat-case-in-terminal-mode) documentation for further information. 

[Note]
> `HEAT` fully relies on containers (`docker.io/plasmapotential/heat:test-build"`); therefore, we will use `podman-hpc` to pull and spawn the container on NERSC. The work is handled via ROSE aaS, so nothing is required from the user’s end.

3. Once you finished 1 and 2 you are ready we will setup HEAT work dir on the remote resources (Perlmutter):
```
HEAT-WORK/
├── HEATrun/
└── output/
```

```sh
mkdir -p HEAT-WORK && mkdir -p HEAT-WORK/HEATrun HEAT-WORK/output
```


4. Update your `amsc.py` `WORK_DIR` and  `DATA_DIR` to use the paths above, and now we can run HEAT with ROSE aaS on Perlmutter:

```sh
python amsc.py
```

5. The `amsc.py` already has `MLFlow` and `ClearML` tracker.


6. To use the `MLFlow` of the `AmSC` servers please setup yours following these instrcutions: [AMSC-MLFLOW-SETUP.md](../AMSC-MLFLOW-SETUP.md)

