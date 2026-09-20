"""Seed HPC demo data — Software, Profiles, Template & Records. Idempotent by stable_key.
Usage: cd backend && source ../.env && PYTHONPATH=. python scripts/seed_demo_data.py
"""
import asyncio, os, uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.db.models import Software, Profile, DataTemplate, TemplateVersion, PerformanceRecord, User

DATA = {
    'software': [
        {'code': 'vasp', 'name': 'VASP', 'version': '6.4.3'},
        {'code': 'lammps', 'name': 'LAMMPS', 'version': '2023.08'},
        {'code': 'gromacs', 'name': 'GROMACS', 'version': '2024.3'},
        {'code': 'openfoam', 'name': 'OpenFOAM', 'version': 'v2212'},
        {'code': 'cp2k', 'name': 'CP2K', 'version': '2024.1'},
    ],
    'profiles': [
        {'code': 'vasp-standard', 'name': 'VASP 标准基准测试', 'sw': 'vasp'},
        {'code': 'vasp-gpu', 'name': 'VASP GPU 加速测试', 'sw': 'vasp'},
        {'code': 'lammps-reaxff', 'name': 'LAMMPS ReaxFF 反应力场', 'sw': 'lammps'},
        {'code': 'lammps-lj', 'name': 'LAMMPS Lennard-Jones 基准', 'sw': 'lammps'},
        {'code': 'gmx-water', 'name': 'GROMACS 水盒子基准', 'sw': 'gromacs'},
        {'code': 'gmx-membrane', 'name': 'GROMACS 膜蛋白模拟', 'sw': 'gromacs'},
        {'code': 'ofoam-lid-driven', 'name': 'OpenFOAM 顶盖驱动流', 'sw': 'openfoam'},
        {'code': 'ofoam-pipe', 'name': 'OpenFOAM 管道湍流', 'sw': 'openfoam'},
        {'code': 'cp2k-water', 'name': 'CP2K 水分子 DFT', 'sw': 'cp2k'},
        {'code': 'cp2k-zeolite', 'name': 'CP2K 沸石体系', 'sw': 'cp2k'},
    ],
    'records': [
        ('vasp', 'vasp-standard', 'vasp-si-64atoms', 'CPU Time', 423.6, 'seconds'),
        ('vasp', 'vasp-standard', 'vasp-si-128atoms', 'CPU Time', 1823.4, 'seconds'),
        ('vasp', 'vasp-gpu', 'vasp-si-64atoms-gpu', 'CPU Time', 87.2, 'seconds'),
        ('vasp', 'vasp-standard', 'vasp-si-64atoms-eff', '并行效率', 79.6, '%'),
        ('vasp', 'vasp-gpu', 'vasp-si-64atoms-gpu-eff', '并行效率', 88.3, '%'),
        ('lammps', 'lammps-reaxff', 'lmp-reaxff-500k', 'CPU Time', 1567.0, 'seconds'),
        ('lammps', 'lammps-lj', 'lmp-lj-1M', '模拟吞吐', 42.5, 'ts/s'),
        ('lammps', 'lammps-reaxff', 'lmp-reaxff-500k-ram', '内存使用', 128.0, 'GB'),
        ('gromacs', 'gmx-water', 'gmx-water-1M', '模拟吞吐', 35.8, 'ns/day'),
        ('gromacs', 'gmx-water', 'gmx-water-1M-eff', '并行效率', 92.1, '%'),
        ('gromacs', 'gmx-membrane', 'gmx-mem-200k', '模拟吞吐', 12.3, 'ns/day'),
        ('openfoam', 'ofoam-lid-driven', 'ofoam-ld-16M', 'CPU Time', 892.0, 'seconds'),
        ('openfoam', 'ofoam-pipe', 'ofoam-pipe-re10k', 'CPU Time', 2104.5, 'seconds'),
        ('cp2k', 'cp2k-water', 'cp2k-h2o-64', 'CPU Time', 942.3, 'seconds'),
        ('cp2k', 'cp2k-water', 'cp2k-h2o-64-eff', '并行效率', 74.8, '%'),
        ('cp2k', 'cp2k-zeolite', 'cp2k-zeo-scf', 'SCF 迭代时间', 156.2, 'seconds'),
        ('vasp', 'vasp-standard', 'vasp-si-64atoms-mem', '内存使用', 64.5, 'GB'),
        ('vasp', 'vasp-gpu', 'vasp-si-64atoms-gpu-energy', 'SCF 收敛能', -1582.4, 'Hartree'),
    ],
}


async def seed():
    db_url = os.getenv('HPC_DATABASE_URL', 'sqlite+aiosqlite:///./hpc.db')
    engine = create_async_engine(db_url)
    async with AsyncSession(engine) as db:
        owner = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        if not owner:
            print('ERROR: no users'); return
        print(f'Owner: {owner.username}')

        sw_map = {}
        for s in DATA['software']:
            ex = (await db.execute(select(Software).where(Software.code == s['code']))).scalar_one_or_none()
            if ex:
                sw_map[s['code']] = ex.id
            else:
                sw = Software(code=s['code'], name=s['name'], version=s['version'])
                db.add(sw); await db.flush(); sw_map[s['code']] = sw.id
                print(f'  + {s["name"]} ({sw.id})')

        pf_map = {}
        for p in DATA['profiles']:
            ex = (await db.execute(select(Profile).where(Profile.code == p['code']))).scalar_one_or_none()
            if ex:
                pf_map[p['code']] = ex.id
            else:
                pf = Profile(software_id=sw_map[p['sw']], code=p['code'], name=p['name'])
                db.add(pf); await db.flush(); pf_map[p['code']] = pf.id
                print(f'  + {p["name"]} ({pf.id})')

        published = (await db.execute(select(TemplateVersion).where(TemplateVersion.status == 'published').limit(1))).scalar_one_or_none()
        tv_id = published.id if published else None
        if not tv_id:
            tmpl = DataTemplate(code='hpc-perf-v1', name='HPC 性能记录模板')
            db.add(tmpl); await db.flush()
            tv = TemplateVersion(template_id=tmpl.id, version_no=1, status='published')
            db.add(tv); await db.flush(); tv_id = tv.id
            print(f'  + Template: {tmpl.name} v1 ({tv.id})')

        count = 0
        for sw_code, pf_code, sk, metric, value, unit in DATA['records']:
            ex = (await db.execute(select(PerformanceRecord).where(PerformanceRecord.stable_key == sk))).scalar_one_or_none()
            if ex: continue
            rec = PerformanceRecord(stable_key=sk, software_id=sw_map[sw_code], profile_id=pf_map[pf_code],
                                    template_version_id=tv_id, owner_user_id=owner.id,
                                    draft_payload={'metric': metric, 'value': value, 'unit': unit})
            db.add(rec); count += 1

        await db.commit()
        total = len((await db.execute(select(PerformanceRecord))).scalars().all())
        print(f'\nDone: new={count} total={total}')
        print(f'  Software: {len(sw_map)}  Profiles: {len(pf_map)}')

if __name__ == '__main__':
    asyncio.run(seed())