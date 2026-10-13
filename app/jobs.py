"""Inline local execution or durable Redis/RQ worker execution."""
import os


def dispatch(db, job):
    if os.getenv('JOB_BACKEND', 'inline') == 'redis':
        from redis import Redis
        from rq import Queue
        try:
            Queue('pdf', connection=Redis.from_url(os.environ['REDIS_URL'])).enqueue(run_job, job.id, job_timeout=1800)
        except Exception:
            db.rollback()
            job.status, job.error = 'failed', '작업 큐에 연결하지 못했습니다.'
            db.commit()
            raise
    elif os.getenv('JOB_BACKEND', 'inline') == 'inline':
        from .multimodal_api import execute_job
        execute_job(db, job)
    else:
        raise ValueError('Unsupported job backend')


def run_job(id):
    from .db import SessionLocal
    from .models import ProcessingJob
    from .multimodal_api import execute_job
    with SessionLocal() as db:
        job = db.get(ProcessingJob, id)
        if job is None or job.status == 'completed':
            return
        execute_job(db, job)
