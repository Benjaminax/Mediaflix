import os
import zipfile

# Prepare content
title = 'Lecture 9: Data Management Layer Design - Notes & Comparison'
sections = [
    ('1. Introduction to Data Management Layer (DML)', [
        'What is the Data Management Layer? - The "library system" of your application',
        'Purpose: Handles how data is stored, retrieved and managed permanently',
        'Importance: Affects performance, scalability, and reliability of entire system',
        '4-Step Design Process: Select Storage Format; Map Problem Domain Objects; Optimize Storage; Design DAM Classes'
    ]),
    ('2. Object Persistence Formats', [
        'Files: sequential and random access — good for simple apps, bad for complex relationships',
        'RDBMS: tables, PK/FK, referential integrity — good for business apps and complex queries',
        'ORDBMS / OODBMS: hybrid and object-first approaches for complex types',
        'NoSQL: key-value, document, columnar; CAP theorem tradeoffs'
    ]),
    ('3. Mapping Problem Domain Objects', [
        'Layer independence: keep business logic separate from storage',
        'Mapping rules: Classes → Tables, Attributes → Columns, Relationships → FKs',
        'Inheritance mapping strategies: single table, per subclass, etc.'
    ]),
    ('4. Optimizing RDBMS Storage', [
        'Normalization (1NF, 2NF, 3NF) to remove redundancy',
        'Denormalization as a performance optimization trade-off',
        'Indexes for query speed; trade-off with write cost',
        'Clustering, volumetrics and capacity planning'
    ]),
    ('5. Data Access and Manipulation (DAM) Classes', [
        'Bridge pattern: DAM sits between business logic and database',
        'Example DAM methods: get, save, delete',
        'ORM frameworks can automate mapping (Hibernate, EF, etc.)'
    ]),
    ('6. Nonfunctional Requirements Impact', [
        'Performance influences indexing and partitioning',
        'Security: access control, encryption, audit trails',
        'Operational: platform constraints, backup/DR',
        'Cultural: data sovereignty and corporate standards'
    ]),
    ('7. Verification and Validation', [
        'Verify mappings and data integrity',
        'Performance and load testing',
        'Security and recovery tests'
    ]),
    ('8. Key Takeaways', [
        'Choose storage based on data complexity and access patterns',
        'Normalize for integrity; denormalize for performance',
        'Keep business logic separate from data access',
        'Watch out for growth and operational constraints'
    ]),
    ("Applying these concepts to Mediaflix (what I changed)", [
        'Added DataManager (SQLite) as a DAM: metadata, provider_cache, watched tables',
        'Kept existing disk image caches; moved text metadata into DB for faster lookup',
        'Wired DataManager into app as self.db and updated ImageItem.load_metadata',
        'DB file: ~/.mediaflix_metadata.db; metadata table indexed on (title, year)'
    ]),
    ('Comparison: Old file-based vs New DB-backed approach', [
        'Old: filesystem-based per-item text files (SYNOPSIS_CACHE_DIR), image files for posters/backdrops',
        'New: SQLite for structured metadata + existing image files retained',
        'Lookup performance: DB SELECT (sub-ms to few ms) vs filesystem stat+open (1-10ms, worse with many files)',
        'Scalability: DB scales much better for thousands of rows; filesystem slows with huge directories',
        'Concurrency: SQLite (WAL) supports concurrent readers; writes should be serialized',
        'Storage: DB compact; images still on disk to avoid DB bloat'
    ]),
    ('Performance Observations (approx)', [
        'SQLite SELECT: ~0.1–5 ms on desktop SSD (indexed)',
        'Filesystem read of small file: ~1–10 ms (depends heavily on directory size)',
        'Network TMDB calls: ~100–400 ms',
        'Benefit: DB hits avoid disk and network latency for UI lists'
    ]),
    ('Pros/Cons and Next Steps', [
        'Pros: faster lookups, centralized cache, easier invalidation, queryable store',
        'Cons: concurrency considerations, need to migrate existing files, slightly more code complexity',
        'Next steps recommended: add a write lock, provide migration script, expand DB usage to episodes and provider cache, add admin tools'
    ])
]

# Build minimal WordprocessingML document.xml content

def make_document_xml(title, sections):
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    parts.append('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">')
    parts.append('<w:body>')

    # Title
    parts.append('<w:p>')
    parts.append('<w:r><w:t>' + escape_xml(title) + '</w:t></w:r>')
    parts.append('</w:p>')

    for heading, bullets in sections:
        parts.append('<w:p>')
        parts.append('<w:r><w:t>' + escape_xml(heading) + '</w:t></w:r>')
        parts.append('</w:p>')
        for b in bullets:
            parts.append('<w:p>')
            parts.append('<w:r><w:t>' + escape_xml('• ' + b) + '</w:t></w:r>')
            parts.append('</w:p>')

    parts.append('<w:sectPr/>')
    parts.append('</w:body>')
    parts.append('</w:document>')
    return '\n'.join(parts)


def escape_xml(s):
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;')
             .replace("'", '&apos;'))

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''

RELS_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''


def create_docx(out_path, title, sections):
    doc_xml = make_document_xml(title, sections)
    # Compose zip
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', RELS_RELS)
        z.writestr('word/document.xml', doc_xml)


if __name__ == '__main__':
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Lecture9_DataManagementLayer_Notes.docx')
    create_docx(out, title, sections)
    print('Wrote', out)
