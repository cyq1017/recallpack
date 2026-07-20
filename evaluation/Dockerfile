FROM python@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e

RUN groupadd --gid 65532 recallpack \
    && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin recallpack

COPY --chown=65532:65532 runner /runner

USER 65532:65532

CMD ["/usr/bin/env", "-i", "HOME=/tmp", "HOSTNAME=recallpack-evaluator", "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1", "/usr/local/bin/python", "/runner/run_tests.py"]
