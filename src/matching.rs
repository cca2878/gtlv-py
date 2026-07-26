//! 矩形最优指派：把 k 个提示词特征指派到 m 个答案格特征（k ≤ m），未被指派的即干扰字。
//!
//! 纯数学后处理，不依赖推理引擎——按 core 的算法契约 `gtlv-core/docs/matching.md` 在本壳内实现
//! （core 只做推理、不提供此 API；各壳按自己语言的惯用法各自实现）。

/// 一次匹配结果：所选答案格序号与距离。
///
/// **提示段序号不单列字段**——返回的 Vec 顺序即提示词左→右序，也就是点击提交顺序。
pub struct Match {
    pub answer_index: usize,
    pub distance: f64,
}

/// 欧氏距离；维度不等视为不可匹配（+∞）。
///
/// **必须用 f64 累加**：特征是 512 维 f32，按 f32 累加的舍入误差足以改变指派结果——
/// 与 Go 壳对拍时实测两边选出不同答案格。契约见 gtlv-core/docs/matching.md。
fn euclidean(a: &[f32], b: &[f32]) -> f64 {
    if a.len() != b.len() {
        return f64::INFINITY;
    }
    a.iter()
        .zip(b)
        .map(|(x, y)| {
            let d = *x as f64 - *y as f64;
            d * d
        })
        .sum::<f64>()
        .sqrt()
}

/// 穷举「k 行 → m 列的单射」取总代价最小者（带最优值剪枝）。
///
/// k ∈ {2,3,4}、m ≤ 8（core 的 MAX_ANS），最坏 8·7·6·5 = 1680 次，纳秒级，无需匈牙利算法。
/// 返回按提示段序（左→右＝点击序）排列的匹配。
pub fn assign(prompt_features: &[Vec<f32>], answer_features: &[Vec<f32>]) -> Vec<Match> {
    let k = prompt_features.len();
    let m = answer_features.len();
    if k == 0 || m < k {
        return Vec::new();
    }

    let cost: Vec<Vec<f64>> = prompt_features
        .iter()
        .map(|prompt| {
            answer_features
                .iter()
                .map(|answer| euclidean(prompt, answer))
                .collect()
        })
        .collect();

    struct Search<'a> {
        k: usize,
        m: usize,
        cost: &'a [Vec<f64>],
        used: Vec<bool>,
        current: Vec<usize>,
        best: f64,
        best_columns: Vec<usize>,
    }

    impl Search<'_> {
        fn visit(&mut self, row: usize, accumulated: f64) {
            if accumulated >= self.best {
                return;
            }
            if row == self.k {
                self.best = accumulated;
                self.best_columns.copy_from_slice(&self.current);
                return;
            }
            for column in 0..self.m {
                if self.used[column] {
                    continue;
                }
                self.used[column] = true;
                self.current[row] = column;
                self.visit(row + 1, accumulated + self.cost[row][column]);
                self.used[column] = false;
            }
        }
    }

    let mut search = Search {
        k,
        m,
        cost: &cost,
        used: vec![false; m],
        current: vec![0; k],
        best: f64::INFINITY,
        best_columns: vec![0; k],
    };
    search.visit(0, 0.0);

    (0..k)
        .map(|row| Match {
            answer_index: search.best_columns[row],
            distance: cost[row][search.best_columns[row]],
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(x: f32) -> Vec<f32> {
        vec![x, 0.0]
    }

    #[test]
    fn picks_nearest_and_skips_distractor() {
        let prompts = vec![v(0.0), v(10.0)];
        let answers = vec![v(9.9), v(5.0), v(0.1)];
        let got = assign(&prompts, &answers);
        assert_eq!(got.len(), 2);
        assert_eq!(got[0].answer_index, 2);
        assert_eq!(got[1].answer_index, 0);
    }

    #[test]
    fn assignment_is_injective_even_when_greedy_would_collide() {
        let prompts = vec![v(0.0), v(0.1)];
        let answers = vec![v(0.05), v(5.0)];
        let got = assign(&prompts, &answers);
        assert_ne!(got[0].answer_index, got[1].answer_index);
    }

    #[test]
    fn returns_empty_when_fewer_tiles_than_targets() {
        assert!(assign(&[v(0.0), v(1.0)], &[v(0.0)]).is_empty());
    }
}
