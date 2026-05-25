import asyncio
import uuid
from sqlalchemy import select

async def clone_and_run(original_case_id: str):
    from app.database import async_session
    from app.models import Case, CaseFile
    from app.services.job_queue import enqueue_full_pipeline

    async with async_session() as db:
        orig = (await db.execute(select(Case).where(Case.id == uuid.UUID(original_case_id)))).scalar_one()

        new_id = uuid.uuid4()
        new_case = Case(
            id=new_id,
            user_id=orig.user_id,
            title=f"[TEST] {orig.title}",
            user_instructions=orig.user_instructions,
            status="draft",
            case_context=dict(orig.case_context) if orig.case_context else {},
            billing_method="vip",
        )
        db.add(new_case)
        await db.flush()

        files = (await db.execute(select(CaseFile).where(CaseFile.case_id == orig.id))).scalars().all()
        for f in files:
            new_file = CaseFile(
                id=uuid.uuid4(),
                case_id=new_id,
                filename=f.filename,
                file_path=f.file_path,
                file_type=f.file_type,
                file_size=f.file_size,
                ocr_status=None,
            )
            db.add(new_file)

        await db.commit()
        print(f"Cloned {original_case_id[:8]} -> {str(new_id)[:8]} ({len(files)} files)")

        await enqueue_full_pipeline(str(new_id), str(orig.user_id), billing_method="vip")
        print(f"Enqueued {str(new_id)[:8]}")
        return str(new_id)

async def main():
    id1 = await clone_and_run("e68649e3-1673-4dfb-9527-5192156cfa9e")
    id2 = await clone_and_run("f4ae7dac-aab2-45e8-b2a3-bca081d68391")
    print(f"\nTest cases: {id1[:8]}, {id2[:8]}")
    print("Monitor: docker compose logs worker --follow | grep -E 'TEST|{id1[:8]}|{id2[:8]}'")

asyncio.run(main())
