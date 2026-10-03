path "manus/data/credentials/*"     { capabilities = ["create", "read", "update", "delete"] }
path "manus/delete/credentials/*"   { capabilities = ["update"] }
path "manus/metadata/credentials/*" { capabilities = ["read", "delete"] }
path "manus/destroy/credentials/*"  { capabilities = ["update"] }
