# Model Compass corpus

The documents and gold annotations Model Compass runs over. `corpus_root` points at
`corpus/` by default, and `shapes.yaml` assigns each docset a shape.

```
corpus/
  docset_name.json                    docset id -> display name
  z4ervk9ic0oo.files_mapping.json     [{name, id, docsetId, ...}], one entry per document
  z4ervk9ic0oo/<docset_id>/
    *.pdf | *.docx                    source documents
    <stem>.dgml.xml                   gold DGML (4 documents per docset)
    <docset>_<org>.ref.json           gold field values, keyed "<file_id>::<Field+Name>"
    <docset>_<org>.ref.type.json      field types
    <docset>_<org>.complex_ref.json   grouped (complex-type) references
    docset_name.json
shapes.yaml                           docset -> shape
```

Orgs are found only through `<org>.files_mapping.json`, and a docset loads only if
`shapes.yaml` lists it. `dgc corpus check` validates the layout.

| Docset | Name | Shape | Documents |
|---|---|---|---:|
| `8frgx7rlbew3` | Sample NTSB Aviation Incident Reports | form | 65 |
| `i0ycfsrfx0av` | Sample Safety Data Sheets | form | 34 |
| `nqkh1hkhhkaf` | Sample Commercial Leases | hybrid_composite | 15 |
| `hcqfkilviuq3` | Sample Master Services Agreements | prose_narrative | 21 |
| `qve3rqreikmn` | Sample Medical Notes (UNC) | prose_narrative | 9 |
| `uzruqpzkyugz` | Sample Clinical Trial Protocols | prose_narrative | 14 |
| `vg52pfjb0wbf` | Sample Transport Agreements | prose_narrative | 20 |
| `yrrrq1d5kili` | Sample Supplier Agreements | prose_narrative | 14 |
| `o9dmulfkp0ii` | Cruise Itineraries | complex_layout | 13 |

No docset has the `table_dense` shape.

Licence: to be confirmed before publication.
