# Client-side environment for the dt-complete service demo -- source me
# in EVERY client terminal (driver and both sensors):
#
#   source deploy/client-env.sh <broker-host>
#
# The client venv comes from digital.twins: ./deploy/install.sh client
# (plus: pip install pandas scikit-learn pyarrow).
#
# DT_BROKER_CERT overrides the pinned-cert path -- needed when this
# machine runs a broker of its own and ~/.radical/orbit/broker_cert.pem
# is that one, not the demo broker's.
BROKER="${1:?usage: source client-env.sh <broker-host>}"

export RADICAL_ORBIT_BROKER_URL="wss://$BROKER:8000"
export RADICAL_ORBIT_BROKER_CERT="${DT_BROKER_CERT:-$HOME/.radical/orbit/broker_cert.pem}"
export DT_STREAM_BACKEND=orbit
