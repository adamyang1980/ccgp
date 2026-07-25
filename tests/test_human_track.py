"""Tests for ccgp_core.human_track module."""

from ccgp_core.human_track import (
    AdvancedHumanTrackGenerator,
    HumanTrackGenerator,
    TrackConfig,
    TrackPoint,
    create_fast_human_track,
    create_human_track,
    create_slow_human_track,
)


class TestHumanTrackGenerator:
    def test_generate_returns_track_points(self):
        gen = HumanTrackGenerator()
        track = gen.generate(260)
        assert len(track) > 0
        assert all(isinstance(p, TrackPoint) for p in track)

    def test_total_x_displacement_matches_distance(self):
        gen = HumanTrackGenerator()
        for distance in [50, 100, 260, 400]:
            track = gen.generate(distance)
            total_x = sum(p.x for p in track)
            assert abs(total_x - distance) < 1.0, (
                f"distance={distance}, total_x={total_x}"
            )

    def test_y_offset_stays_bounded(self):
        gen = HumanTrackGenerator()
        track = gen.generate(260)
        cumulative_y = 0
        for p in track:
            cumulative_y += p.y
            assert abs(cumulative_y) < 20, "Y offset exceeded bounds"

    def test_delays_are_positive(self):
        gen = HumanTrackGenerator()
        track = gen.generate(260)
        for p in track:
            assert p.delay >= 0

    def test_total_duration_in_range(self):
        config = TrackConfig(min_duration=0.5, max_duration=1.0)
        gen = HumanTrackGenerator(config)
        track = gen.generate(260)
        total_time = sum(p.delay for p in track)
        # Allow some margin for start delay and correction points
        assert 0.3 < total_time < 3.0

    def test_small_distance_no_overshoot(self):
        gen = HumanTrackGenerator()
        track = gen.generate(30)
        total_x = sum(p.x for p in track)
        assert abs(total_x - 30) < 1.0

    def test_generate_as_dict_format(self):
        gen = HumanTrackGenerator()
        track = gen.generate_as_dict(100)
        assert len(track) > 0
        for p in track:
            assert "x" in p
            assert "y" in p
            assert "delay" in p


class TestAdvancedHumanTrackGenerator:
    def test_inherits_base_behavior(self):
        gen = AdvancedHumanTrackGenerator()
        track = gen.generate(260)
        total_x = sum(p.x for p in track)
        assert abs(total_x - 260) < 1.0

    def test_y_includes_bezier_component(self):
        gen = AdvancedHumanTrackGenerator()
        track = gen.generate(260)
        # Advanced generator should have non-zero Y values
        y_values = [p.y for p in track]
        assert any(abs(y) > 0.01 for y in y_values)


class TestFactoryFunctions:
    def test_create_human_track_default(self):
        track = create_human_track(200)
        assert len(track) > 0
        total_x = sum(p["x"] for p in track)
        assert abs(total_x - 200) < 1.0

    def test_create_human_track_basic(self):
        track = create_human_track(200, advanced=False)
        assert len(track) > 0

    def test_create_fast_human_track(self):
        track = create_fast_human_track(150)
        total_time = sum(p["delay"] for p in track)
        assert total_time < 2.0  # Fast track should be short

    def test_create_slow_human_track(self):
        track = create_slow_human_track(150)
        total_time = sum(p["delay"] for p in track)
        assert total_time > 0.3  # Slow track should be longer

    def test_custom_duration(self):
        gen = HumanTrackGenerator()
        track = gen.generate(200, duration=0.8)
        total_x = sum(p.x for p in track)
        assert abs(total_x - 200) < 1.0
