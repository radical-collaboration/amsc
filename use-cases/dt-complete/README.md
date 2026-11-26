
# DT-Complete

A demonstration of a complete digital twin:

2 sensors + 3 surrogates* / physics entities

Sensors:
- M3DC1 Mock sensor
- Random Value sensor

Three physical entities:
- M3DC1 Investigator
- Runs a M3DC1 Investigator
- Runs a DEMO_AGENT Agent (a simple pass through)
- Runs a NEGATIVE_Agent Agent (simply computes the negative of sensor input)

> *Technically, the M3DC1 trains two surrogates and then picks the best one.


**Digital Twin Description Graph:**
```

M3DC1 Mock sensor --> M3DC1 Investigator --
                                           \ 
                                            --(JOIN)--> DEMO Agent --> OUT  
RAND_VAL sensor  ---> NEGATIVE_Agent ------/

```



## To run

Both paths run against the DT framework commit that `deploy/install.sh`
on the `devel` branch of
[radical-cybertools/digital.twins](https://github.com/radical-cybertools/digital.twins)
pins; the `release/vanilla-framework` branch is not needed.  The framework's
documentation (concepts, tutorials, limits) is in its `docs/`.

### As a service

The ORBIT broker with the DT service plugin runs on a standalone host,
the compute on a Perlmutter allocation, and the sensors and the client
(`run_me_service.py`) on your machine.  [deploy/README.md](deploy/README.md)
has the setup and run steps used for the recorded demo.

### Locally

`run_me.py` runs the same twin in one process, on the same pinned stack.
`install.sh` needs `python3.12` (or set `DT_PYTHON` to another
interpreter).

1. Install the framework and the use case's extra dependencies:

   ```bash
   git clone -b devel https://github.com/radical-cybertools/digital.twins
   (cd digital.twins && ./deploy/install.sh client)      # venv: ./ve.demo
   ./digital.twins/ve.demo/bin/pip install pandas scikit-learn pyarrow
   . digital.twins/ve.demo/bin/activate
   ```

2. Start the PUB/SUB streaming broker: `python3 local_broker.py`
3. Start the sensors, each in its own terminal:
   `python3 m3dc1/m3dc1_mock_sensor.py` and
   `python3 negative_agent/rand_sensor.py`
4. Run the twin: `python3 run_me.py`

> The framework package is being renamed from `digitaltwin` to
> `radical.doppelganger` for its first release.  This use case imports
> `digitaltwin` and runs against the commit `deploy/install.sh` pins; it
> moves to the new name with that release.
