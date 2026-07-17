# CDK Scaffold

Minimal AWS CDK (Python) starter with a single `DataStack` containing a DynamoDB table + GSI.

## Prerequisites

- Python 3.9+
- Node.js (for the CDK CLI)
- AWS credentials configured (`aws configure` or env vars)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate         # Windows: source.bat
pip install -r requirements.txt
```

## One-time per account/region

```bash
npx aws-cdk bootstrap
```

## Deploy / destroy

```bash
npx aws-cdk synth                 # render CloudFormation to cdk.out/
npx aws-cdk deploy                # deploy DataStack
npx aws-cdk destroy               # tear down
```

## Layout

```
app.py               # CDK app entry — instantiates stacks
stacks/
  data_stack.py      # DynamoDB table + GSI
requirements.txt     # aws-cdk-lib, constructs
cdk.json             # CDK config + feature flags
```

Add new stacks under `stacks/` and wire them into `app.py`.
