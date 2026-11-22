const miembros = [
  { _id: 0, host: "mongo1:27017" },
  { _id: 1, host: "mongo2:27017" },
  { _id: 2, host: "mongo3:27017" },
];

try {
  rs.status();
  print("replica set rs0 ya inicializado");
} catch (e) {
  rs.initiate({ _id: "rs0", members: miembros });
  print("replica set rs0 inicializado");
}

function hayPrimario() {
  try {
    return rs.status().members.some((m) => m.stateStr === "PRIMARY");
  } catch (e) {
    return false;
  }
}

for (let i = 0; i < 60 && !hayPrimario(); i++) {
  sleep(1000);
}

if (!hayPrimario()) {
  print("no se eligió primario en 60 s");
  quit(1);
}

print("primario elegido");
