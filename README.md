# nostr-publisher-template

Mini proyecto base en Rust para publicar notas en Nostr con `nostr-sdk 0.44.1`.

## Qué hace

- carga `NOSTR_NSEC` o `--secret-key`
- carga relays desde `--relay` y/o `NOSTR_RELAYS`
- usa un set base de relays embebidos si no das ninguno
- puedes ampliar el set embebido con `--all-relays`
- normaliza relays quitando `/` final y deduplica la lista
- publica un `kind 1` text note
- imprime `event_id`, relays exitosos/fallidos
- intenta verificar el evento por `id` en los relays configurados

## Prioridad de relays

1. `--relay` repetido en CLI
2. `NOSTR_RELAYS` como lista separada por comas
3. relays embebidos por defecto
4. si pasas `--all-relays`, añade también la lista expandida

## Uso rápido

```bash
cp .env.example .env
# completa NOSTR_NSEC y, si quieres, NOSTR_RELAYS
cargo run -- --content "Hola Nostr"
```

O con flags:

```bash
cargo run -- \
  --secret-key "nsec1..." \
  --relay wss://relay.damus.io \
  --relay wss://nos.lol/ \
  --content "Hola Nostr"
```

Para usar la lista extendida:

```bash
cargo run -- --all-relays --content "Hola Nostr"
```

## Notas

- `npub` no alcanza para publicar.
- Si no hay relays explícitos, el binario usa el set base embebido.
- La verificación por relay puede tardar un poco según indexación.
- Las URLs se normalizan para eliminar slash final, así que `wss://nos.lol/` y `wss://nos.lol` se tratan igual.
