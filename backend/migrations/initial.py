from sqlalchemy import text, inspect
from src.config.database import Base, engine
from src import models
def migrate():
    Base.metadata.create_all(engine)
    # 既有库的 datasets 表补充发布批次列；新列均为可空或有默认值，存量行不受影响
    with engine.begin() as conn:
        existing={c['name'] for c in inspect(conn).get_columns('datasets')}
        additions={
            'kind':"VARCHAR(20) NOT NULL DEFAULT 'manual'",
            'month':'VARCHAR(7) NULL',
            'batch_no':'INTEGER NULL',
            'publish_order_id':'INTEGER NULL',
            'superseded':'BOOLEAN NOT NULL DEFAULT FALSE',
        }
        for name,ddl in additions.items():
            if name not in existing:
                conn.execute(text(f'ALTER TABLE datasets ADD COLUMN {name} {ddl}'))
        try:
            conn.execute(text('CREATE UNIQUE INDEX uq_datasets_publish_order ON datasets (publish_order_id)'))
        except Exception:
            pass # 索引已存在或方言不支持时跳过，模型层唯一约束仍生效
if __name__=='__main__':migrate()
