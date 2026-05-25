import asyncio
import json
import sys
sys.path.insert(0, '/app')

async def main():
    from app.database import async_session
    from app.models import Case
    from sqlalchemy import select
    from app.services.reference_extractor import extract_legal_references
    from app.services.norm_lookup import lookup_references

    case_id = 'ea3dab2b-cc06-465b-9119-ce10942a4bcb'
    
    async with async_session() as db:
        case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one()
        text = case.final_text or case.generated_text
        print(f'Text length: {len(text)}')
        
        refs = extract_legal_references(text)
        print(f'Found {len(refs)} references')
        
        if not refs:
            print('No references found, nothing to validate')
            return
        
        refs_with_lookup = await lookup_references(refs, db)
        
        validation = {
            'references': [
                {
                    'raw': r['raw'], 'type': r['type'],
                    'position': r['position'], 'end_position': r['end_position'],
                    'status': 'found' if r.get('db_status') == 'found' else 'not_found',
                    'norm_id': str(r['norm_id']) if r.get('norm_id') else None,
                    'doc_title': r.get('doc_title'),
                }
                for r in refs_with_lookup
            ],
            'stats': {
                'total': len(refs_with_lookup),
                'found': sum(1 for r in refs_with_lookup if r.get('db_status') == 'found'),
                'not_found': sum(1 for r in refs_with_lookup if r.get('db_status') != 'found'),
            },
        }
        
        case.validation_result = validation
        await db.commit()
        
        print(f'Validation saved: {validation["stats"]}')
        
        # Also verify positions match
        for ref in validation['references'][:3]:
            actual = text[ref['position']:ref['end_position']]
            match = '✓' if actual == ref['raw'] else '✗'
            print(f'  {match} pos {ref["position"]}-{ref["end_position"]}: "{actual[:60]}" vs "{ref["raw"][:60]}"')

asyncio.run(main())
