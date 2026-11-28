# Examples

## Use cases

- Switch the receiver to a movie input and listening mode when the projector turns on.
- Lower the volume at night and turn late night mode on (Low, High or Auto).
- Put the receiver in standby when the room has been empty for an hour.
- Pick the Dirac Live slot for movies or for music.

## Automation: movie scene

Replace the entity names with yours.

```yaml
automation:
  - alias: Movie time
    triggers:
      - trigger: state
        entity_id: media_player.projector
        to: "on"
    actions:
      - action: media_player.turn_on
        target:
          entity_id: media_player.onkyo_tx_rz50_main_zone
      - action: media_player.select_source
        target:
          entity_id: media_player.onkyo_tx_rz50_main_zone
        data:
          source: Game
      - action: select.select_option
        target:
          entity_id: select.onkyo_tx_rz50_dirac_live
        data:
          option: Slot 1
```

## Automation: quiet night

```yaml
automation:
  - alias: Quiet night
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: media_player.volume_set
        target:
          entity_id: media_player.onkyo_tx_rz50_main_zone
        data:
          volume_level: 0.25
      - action: select.select_option
        target:
          entity_id: select.onkyo_tx_rz50_late_night
        data:
          option: Low
```

## Send any command

```yaml
action: onkyo_eiscp.send_raw
data:
  config_entry_id: 0123456789abcdef
  message: MVLQSTN
```

The reply comes back in `replies`. Use Developer tools, Actions, to find your entry id.
