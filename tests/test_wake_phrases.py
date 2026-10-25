from jarvis.voice.wake import WakeWordListener


def test_match_czech_phrases():
    wake = WakeWordListener()
    assert wake.match_transcript("Hej Adame otevři projekt")
    assert wake.match_transcript("Adame, co děláš?")
    assert wake.match_transcript("adame")
    assert wake.match_transcript("hej adam")
    assert not wake.match_transcript("otevři prohlížeč")
