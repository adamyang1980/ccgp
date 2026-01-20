"""
人类滑动轨迹生成器 - 用于滑块验证码破解

基于阿里云滑块验证码行为检测机制分析，实现以下特征：
1. 五阶段运动模型（启动-加速-匀速-减速-微调）
2. 高斯分布抖动
3. 多种过冲模式
4. 时间随机化
5. 贝塞尔曲线轨迹
"""

import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class TrackPoint:
    """轨迹点"""
    x: float  # X轴增量
    y: float  # Y轴增量
    delay: float  # 延迟（秒）


@dataclass
class TrackConfig:
    """轨迹生成配置"""
    # 时间参数（秒）
    min_duration: float = 0.4
    max_duration: float = 1.2
    
    # 起始停顿（秒）
    min_start_delay: float = 0.05
    max_start_delay: float = 0.20
    
    # 阶段比例
    startup_ratio: float = 0.05      # 启动阶段
    acceleration_ratio: float = 0.25  # 加速阶段
    cruise_ratio: float = 0.40        # 匀速阶段
    deceleration_ratio: float = 0.25  # 减速阶段
    adjust_ratio: float = 0.05        # 微调阶段
    
    # 抖动参数（像素）
    x_jitter_sigma: float = 0.5  # X轴抖动标准差
    y_jitter_sigma: float = 1.5  # Y轴抖动标准差
    
    # 过冲参数
    no_overshoot_prob: float = 0.30    # 无过冲概率
    small_overshoot_prob: float = 0.50  # 小过冲概率
    small_overshoot_min: int = 5
    small_overshoot_max: int = 10
    large_overshoot_min: int = 10
    large_overshoot_max: int = 20
    
    # 步间延迟（秒）
    min_step_delay: float = 0.008
    max_step_delay: float = 0.025


class HumanTrackGenerator:
    """人类轨迹生成器"""
    
    def __init__(self, config: Optional[TrackConfig] = None):
        self.config = config or TrackConfig()
    
    def _gaussian_jitter(self, sigma: float) -> float:
        """生成高斯分布的抖动值"""
        return random.gauss(0, sigma)
    
    def _bezier_curve(self, t: float, p0: float, p1: float, p2: float, p3: float) -> float:
        """三次贝塞尔曲线计算"""
        u = 1 - t
        return (u * u * u * p0 +
                3 * u * u * t * p1 +
                3 * u * t * t * p2 +
                t * t * t * p3)
    
    def _ease_in_out_cubic(self, t: float) -> float:
        """缓入缓出三次函数"""
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 3) / 2
    
    def _ease_out_quart(self, t: float) -> float:
        """缓出四次函数"""
        return 1 - pow(1 - t, 4)
    
    def _ease_in_out_quint(self, t: float) -> float:
        """缓入缓出五次函数"""
        if t < 0.5:
            return 16 * t * t * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 5) / 2
    
    def _get_random_easing(self):
        """随机选择缓动函数"""
        easings = [
            self._ease_in_out_cubic,
            self._ease_out_quart,
            self._ease_in_out_quint,
        ]
        return random.choice(easings)
    
    def _calculate_overshoot(self, distance: int) -> Tuple[int, bool]:
        """
        计算过冲量
        
        Returns:
            Tuple[int, bool]: (过冲量, 是否需要回调)
        """
        if distance < 50:
            return 0, False
        
        rand = random.random()
        
        if rand < self.config.no_overshoot_prob:
            # 无过冲
            return 0, False
        elif rand < self.config.no_overshoot_prob + self.config.small_overshoot_prob:
            # 小过冲
            overshoot = random.randint(
                self.config.small_overshoot_min,
                self.config.small_overshoot_max
            )
            return overshoot, True
        else:
            # 大过冲
            overshoot = random.randint(
                self.config.large_overshoot_min,
                self.config.large_overshoot_max
            )
            return overshoot, True
    
    def _generate_phase_points(
        self,
        start_progress: float,
        end_progress: float,
        start_pos: float,
        end_pos: float,
        num_points: int,
        easing_func
    ) -> List[float]:
        """生成某一阶段的位置点"""
        points = []
        for i in range(num_points):
            t = i / max(num_points - 1, 1)
            # 将阶段内的进度映射到缓动函数
            eased_t = easing_func(t)
            pos = start_pos + (end_pos - start_pos) * eased_t
            points.append(pos)
        return points
    
    def generate(self, distance: int, duration: Optional[float] = None) -> List[TrackPoint]:
        """
        生成人类滑动轨迹
        
        Args:
            distance: 滑动目标距离（像素）
            duration: 可选的总时长（秒），不指定则随机生成
        
        Returns:
            List[TrackPoint]: 轨迹点列表
        """
        if duration is None:
            duration = random.uniform(
                self.config.min_duration,
                self.config.max_duration
            )
        
        # 计算过冲
        overshoot, need_correction = self._calculate_overshoot(distance)
        target_with_overshoot = distance + overshoot
        
        # 计算各阶段的时间分配
        cfg = self.config
        phases = [
            (cfg.startup_ratio, 0, 0.02),           # 启动：0% -> 2%
            (cfg.acceleration_ratio, 0.02, 0.40),   # 加速：2% -> 40%
            (cfg.cruise_ratio, 0.40, 0.85),         # 匀速：40% -> 85%
            (cfg.deceleration_ratio, 0.85, 1.0),    # 减速：85% -> 100%
        ]
        
        # 确定每个阶段的点数（基于时间比例）
        total_steps = max(int(duration / 0.015), 20)  # 约15ms一个点
        
        all_positions = []
        easing_func = self._get_random_easing()
        
        for ratio, pos_start, pos_end in phases:
            phase_steps = max(int(total_steps * ratio), 2)
            start_val = target_with_overshoot * pos_start
            end_val = target_with_overshoot * pos_end
            
            phase_points = self._generate_phase_points(
                pos_start, pos_end,
                start_val, end_val,
                phase_steps,
                easing_func
            )
            all_positions.extend(phase_points)
        
        # 添加过冲回调阶段
        if need_correction and overshoot > 0:
            current_pos = target_with_overshoot
            correction_steps = random.randint(8, 15)
            
            for i in range(correction_steps):
                # 非线性回调（快速然后变慢）
                progress = i / correction_steps
                step_size = overshoot * (1 - progress) * 0.3
                step_size = max(step_size, 0.5)  # 确保每步至少移动0.5px
                
                current_pos -= step_size
                if current_pos <= distance:
                    current_pos = distance
                    all_positions.append(current_pos)
                    break
                all_positions.append(current_pos)
            
            # 确保最后一个位置就是目标距离
            if all_positions[-1] != distance:
                all_positions.append(float(distance))
        else:
            # 无过冲时确保最后一个位置就是目标距离
            if all_positions and abs(all_positions[-1] - distance) > 0.1:
                all_positions.append(float(distance))
        
        # 生成轨迹点（增量形式）
        track = []
        
        # 添加起始停顿
        start_delay = random.uniform(
            self.config.min_start_delay,
            self.config.max_start_delay
        )
        track.append(TrackPoint(x=0, y=0, delay=start_delay))
        
        prev_pos = 0
        cumulative_y = 0
        cumulative_x = 0  # 跟踪累积的X位移
        
        for i, pos in enumerate(all_positions):
            # 计算X轴增量 - 不添加抖动，保持精确距离
            x_delta = pos - prev_pos
            
            # 生成Y轴抖动（使用高斯分布）- 仅在Y轴上添加人类特征
            y_jitter = self._gaussian_jitter(self.config.y_jitter_sigma)
            
            # 限制Y轴累积偏移，避免滑出轨道
            if abs(cumulative_y + y_jitter) > 10:
                y_jitter = -cumulative_y * 0.3  # 回中
            cumulative_y += y_jitter
            
            # 生成非均匀延迟
            base_delay = random.uniform(
                self.config.min_step_delay,
                self.config.max_step_delay
            )
            
            # 在某些点上添加额外的微停顿（模拟人类犹豫）
            if random.random() < 0.05:  # 5%概率
                base_delay += random.uniform(0.02, 0.08)
            
            track.append(TrackPoint(
                x=x_delta,
                y=y_jitter,
                delay=base_delay
            ))
            
            cumulative_x += x_delta
            prev_pos = pos
        
        # 最终距离补偿：确保总X位移精确等于目标距离
        final_diff = distance - cumulative_x
        if abs(final_diff) > 0.01:
            # 添加一个补偿点
            track.append(TrackPoint(
                x=final_diff,
                y=0,
                delay=random.uniform(0.01, 0.02)
            ))
        
        return track
    
    def generate_as_dict(self, distance: int, duration: Optional[float] = None) -> List[dict]:
        """
        生成轨迹并返回字典列表（兼容现有代码）
        
        Args:
            distance: 滑动目标距离
            duration: 可选的总时长
        
        Returns:
            List[dict]: 格式为 [{"x": float, "y": float, "delay": float}, ...]
        """
        track = self.generate(distance, duration)
        return [{"x": p.x, "y": p.y, "delay": p.delay} for p in track]


class AdvancedHumanTrackGenerator(HumanTrackGenerator):
    """高级人类轨迹生成器 - 增加贝塞尔曲线和速度建模"""
    
    def __init__(self, config: Optional[TrackConfig] = None):
        super().__init__(config)
    
    def _generate_bezier_y_curve(self, num_points: int) -> List[float]:
        """
        使用贝塞尔曲线生成Y轴的自然弧线
        模拟人类滑动时手指/鼠标的自然弧形轨迹
        """
        # 随机控制点，创造自然的弧形
        p0 = 0
        p1 = random.uniform(-3, 3)   # 第一个控制点
        p2 = random.uniform(-3, 3)   # 第二个控制点
        p3 = random.uniform(-1, 1)   # 终点（略微偏离）
        
        y_values = []
        for i in range(num_points):
            t = i / max(num_points - 1, 1)
            y = self._bezier_curve(t, p0, p1, p2, p3)
            y_values.append(y)
        
        return y_values
    
    def generate(self, distance: int, duration: Optional[float] = None) -> List[TrackPoint]:
        """
        生成带有贝塞尔Y轴曲线的高级人类轨迹
        """
        # 先生成基础轨迹
        base_track = super().generate(distance, duration)
        
        if len(base_track) < 3:
            return base_track
        
        # 生成贝塞尔Y轴曲线
        bezier_y = self._generate_bezier_y_curve(len(base_track))
        
        # 将贝塞尔曲线叠加到原有抖动上
        enhanced_track = []
        for i, point in enumerate(base_track):
            # 叠加贝塞尔曲线的Y值
            new_y = point.y + bezier_y[i]
            enhanced_track.append(TrackPoint(
                x=point.x,
                y=new_y,
                delay=point.delay
            ))
        
        return enhanced_track


# ========== 工厂函数 ==========

def create_human_track(
    distance: int,
    duration: Optional[float] = None,
    advanced: bool = True
) -> List[dict]:
    """
    创建人类滑动轨迹的便捷函数
    
    Args:
        distance: 滑动目标距离（像素）
        duration: 可选的总时长（秒）
        advanced: 是否使用高级生成器（含贝塞尔曲线）
    
    Returns:
        List[dict]: 轨迹点列表
    
    Example:
        >>> track = create_human_track(260)
        >>> for point in track:
        ...     await page.mouse.move(x + point["x"], y + point["y"])
        ...     await asyncio.sleep(point["delay"])
    """
    if advanced:
        generator = AdvancedHumanTrackGenerator()
    else:
        generator = HumanTrackGenerator()
    
    return generator.generate_as_dict(distance, duration)


def create_fast_human_track(distance: int) -> List[dict]:
    """创建快速人类轨迹（0.3-0.6秒）"""
    config = TrackConfig(
        min_duration=0.3,
        max_duration=0.6,
        min_start_delay=0.03,
        max_start_delay=0.10,
    )
    generator = AdvancedHumanTrackGenerator(config)
    return generator.generate_as_dict(distance)


def create_slow_human_track(distance: int) -> List[dict]:
    """创建慢速人类轨迹（0.8-1.5秒）- 更谨慎的用户"""
    config = TrackConfig(
        min_duration=0.8,
        max_duration=1.5,
        min_start_delay=0.10,
        max_start_delay=0.30,
        y_jitter_sigma=2.0,  # 更多抖动
    )
    generator = AdvancedHumanTrackGenerator(config)
    return generator.generate_as_dict(distance)


# ========== 测试 ==========

if __name__ == "__main__":
    import json
    
    print("=" * 60)
    print("人类轨迹生成器测试")
    print("=" * 60)
    
    # 测试基础生成器
    print("\n[1] 基础轨迹生成器:")
    basic_gen = HumanTrackGenerator()
    basic_track = basic_gen.generate_as_dict(260)
    print(f"    生成 {len(basic_track)} 个点")
    print(f"    总时长: {sum(p['delay'] for p in basic_track):.3f}s")
    print(f"    总X位移: {sum(p['x'] for p in basic_track):.1f}px")
    
    # 测试高级生成器
    print("\n[2] 高级轨迹生成器 (含贝塞尔曲线):")
    advanced_gen = AdvancedHumanTrackGenerator()
    advanced_track = advanced_gen.generate_as_dict(260)
    print(f"    生成 {len(advanced_track)} 个点")
    print(f"    总时长: {sum(p['delay'] for p in advanced_track):.3f}s")
    print(f"    总X位移: {sum(p['x'] for p in advanced_track):.1f}px")
    
    # 测试便捷函数
    print("\n[3] 便捷函数测试:")
    fast_track = create_fast_human_track(260)
    slow_track = create_slow_human_track(260)
    print(f"    快速轨迹: {len(fast_track)} 点, {sum(p['delay'] for p in fast_track):.3f}s")
    print(f"    慢速轨迹: {len(slow_track)} 点, {sum(p['delay'] for p in slow_track):.3f}s")
    
    # 输出一个完整轨迹示例
    print("\n[4] 轨迹示例 (前10个点):")
    for i, p in enumerate(advanced_track[:10]):
        print(f"    #{i:2d}: x={p['x']:+7.2f}, y={p['y']:+6.2f}, delay={p['delay']:.4f}s")
    
    print("\n" + "=" * 60)
    print("测试完成!")
