### How To RUN M3DC1 via ROSE aaS

1- Follow the steps in our service core layer [radical.edge](https://github.com/radical-cybertools/radical.edge/blob/feature/amsc/README_amsc.md)

2- Once you have succefully created the env, setup your ceritficates and your bridge/tokens install SURGE from this repo: [SURGE](https://github.com/S-Villar/SURGE/tree/radical-integration/examples/rose_orchestration)

3- Once you finished 1 and 2 you are ready to run on aaS on Perlmutter using `python 04_example_parallel_model_race_service.py --max-iter 10 --growing-pool`

5- The `04_example_parallel_model_race_service.py` already has `MLFlow` and `ClearML` tracker.

6- To use the `MLFlow` of the `AmSC` servers please setup yours following these instrcutions: [setup-mlflow-with-amsc](https://gist.github.com/AymenFJA/0db6dcd357889546fde17a717ec2b417)

### Sample output of the client side (your machine):
```shell
2026-05-01 23:53:52,807 | DEBUG    | [urllib3.connectionpool] | https://mlflow.american-science-cloud.org:443 "POST /api/2.0/mlflow/runs/set-tag HTTP/1.1" 200 2
2026-05-01 23:53:53,341 | DEBUG    | [urllib3.connectionpool] | https://mlflow.american-science-cloud.org:443 "GET /api/2.0/mlflow/runs/get?run_uuid=4004567fd2244c23a6115e5cee6ccd15&run_id=4004567fd2244c23a6115e5cee6ccd15 HTTP/1.1" 200 None
2026-05-01 23:53:53,870 | DEBUG    | [urllib3.connectionpool] | https://mlflow.american-science-cloud.org:443 "POST /api/2.0/mlflow/runs/update HTTP/1.1" 200 None
2026-05-01 23:53:57,639 | INFO     | [rhapsody.backends.execution.edge] | Edge execution backend shutdown complete
2026-05-01 23:53:57,639 | DEBUG    | [radical.asyncflow.workflow_manager] | Shutting down execution backend completed
2026-05-01 23:53:57,639 | INFO     | [radical.asyncflow.workflow_manager] | Shutdown completed for all components.
SURGE candidates: 100%|█████████████| 20/20 [17:22<00:00, 52.12s/model, learner=rf, r2=0.8577, rmse=0.008258]

Example 4 summary
Wall time: 1052.1s
rank  learner   workflow         val_r2    val_rmse  run_tag
   1  rf        m3dc1_rf        0.90178    0.006715  rose_parallel_0_rf_m3dc1_rf_iter_7
   2  mlp       m3dc1_mlp       0.88985    0.007111  rose_parallel_1_mlp_m3dc1_mlp_iter_7
   3  mlp       m3dc1_mlp       0.87184    0.007838  rose_parallel_1_mlp_m3dc1_mlp_iter_9
   4  mlp       m3dc1_mlp       0.87059    0.007829  rose_parallel_1_mlp_m3dc1_mlp_iter_6
   5  mlp       m3dc1_mlp       0.86549    0.008016  rose_parallel_1_mlp_m3dc1_mlp_iter_8
   6  rf        m3dc1_rf        0.85774    0.008258  rose_parallel_0_rf_m3dc1_rf_iter_9
   7  rf        m3dc1_rf        0.85564    0.008304  rose_parallel_0_rf_m3dc1_rf_iter_8
   8  mlp       m3dc1_mlp       0.85108    0.007635  rose_parallel_1_mlp_m3dc1_mlp_iter_2
   9  rf        m3dc1_rf        0.85078    0.008407  rose_parallel_0_rf_m3dc1_rf_iter_6
  10  rf        m3dc1_rf        0.83884    0.008262  rose_parallel_0_rf_m3dc1_rf_iter_0
  11  rf        m3dc1_rf        0.82106    0.009766  rose_parallel_0_rf_m3dc1_rf_iter_5
  12  mlp       m3dc1_mlp       0.81888    0.009825  rose_parallel_1_mlp_m3dc1_mlp_iter_5
  13  rf        m3dc1_rf        0.81817    0.008437  rose_parallel_0_rf_m3dc1_rf_iter_2
  14  mlp       m3dc1_mlp       0.80211    0.009156  rose_parallel_1_mlp_m3dc1_mlp_iter_0
  15  rf        m3dc1_rf        0.78874    0.009247  rose_parallel_0_rf_m3dc1_rf_iter_4
  16  mlp       m3dc1_mlp       0.78610    0.009647  rose_parallel_1_mlp_m3dc1_mlp_iter_3
  17  mlp       m3dc1_mlp       0.78291    0.009373  rose_parallel_1_mlp_m3dc1_mlp_iter_4
  18  rf        m3dc1_rf        0.77148    0.009971  rose_parallel_0_rf_m3dc1_rf_iter_3
  19  rf        m3dc1_rf        0.60951    0.012579  rose_parallel_0_rf_m3dc1_rf_iter_1
  20  mlp       m3dc1_mlp       0.57626    0.013103  rose_parallel_1_mlp_m3dc1_mlp_iter_1
Workspace: /home/aymen/RADICAL/M3CD1-AMSC-MAY-DEMO/SURGE/examples/rose_orchestration/workspace/example_04
Log file:  /home/aymen/RADICAL/M3CD1-AMSC-MAY-DEMO/SURGE/examples/rose_orchestration/workspace/example_04/execution.log

— Tearing down resources we created —
  cancelled PsiJ job 062b92f3-e175-4e8b-9c00-39025f96eff6 on perlmutter

Done.
```
