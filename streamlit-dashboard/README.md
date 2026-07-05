# SU MöDLING Swimming Results Dashboard

Streamlit dashboard for SU MöDLING swimming competition results.

## Local development

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Fill in real token values in secrets.toml (run generate_streamlit_token.py)
streamlit run app.py
```

## Deployment

Deployed on [Streamlit Community Cloud](https://share.streamlit.io).
Source: this repo, entry point `streamlit-dashboard/app.py`.
Secrets are stored in the Streamlit Cloud app settings (never in git).
