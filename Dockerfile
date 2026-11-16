FROM node:24-bookworm-slim AS ui
WORKDIR /source
RUN npm install -g pnpm@11.25.0
COPY ui/package.json ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ./ui/
RUN cd ui && pnpm install --frozen-lockfile
COPY ui ./ui
COPY spec ./spec
COPY version.json ./version.json
RUN cd ui && pnpm build

FROM python:3.12-slim-bookworm AS server
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CORTE_DATA_DIR=/var/lib/corte CORTE_UI_DIR=/app/ui/dist
WORKDIR /app
COPY cloud/requirements.txt cloud/requirements.lock.txt ./cloud/
RUN pip install --no-cache-dir -r cloud/requirements.lock.txt \
    && groupadd --gid 10001 corte \
    && useradd --uid 10001 --gid corte --no-create-home corte \
    && mkdir -p /var/lib/corte && chown corte:corte /var/lib/corte
COPY --chown=corte:corte hub/creatorhub ./hub/creatorhub
COPY --chown=corte:corte cloud/*.py ./cloud/
COPY --chown=corte:corte cloud/google/__init__.py cloud/google/bootstrap.py ./cloud/google/
COPY --chown=corte:corte version.json ./version.json
COPY --from=ui --chown=corte:corte /source/ui/dist ./ui/dist
USER corte
EXPOSE 10000
CMD ["gunicorn", "-c", "cloud/gunicorn.conf.py", "cloud.app:create_app()"]
