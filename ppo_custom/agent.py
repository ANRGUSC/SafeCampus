import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import os
from datetime import datetime
import logging
from collections import deque
import random
import itertools
from tqdm import tqdm
from .utilities import load_config
from .visualizer import visualize_all_states, visualize_q_table, visualize_variance_in_rewards_heatmap, \
    visualize_explained_variance, visualize_variance_in_rewards, visualize_infected_vs_community_risk_table, \
    states_visited_viz
import wandb
from torch.optim.lr_scheduler import StepLR
import math
import scipy.stats as stats
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.interpolate import make_interp_spline
import torch.nn.functional as F
from torch.distributions.categorical import Categorical
def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

# Set seed for reproducibility
set_seed(100)  # Replace 42 with your desired seed value

class ExplorationRateDecay:
    def __init__(self, max_episodes, min_exploration_rate, initial_exploration_rate):
        self.max_episodes = max_episodes
        self.min_exploration_rate = min_exploration_rate
        self.initial_exploration_rate = initial_exploration_rate
        self.current_decay_function = 1  # Variable to switch between different decay functions

    def set_decay_function(self, decay_function_number):
        self.current_decay_function = decay_function_number

    def get_exploration_rate(self, episode):
        if self.current_decay_function == 1:  # Exponential Decay
            exploration_rate = self.initial_exploration_rate * np.exp(-episode / self.max_episodes)
        elif self.current_decay_function == 2:  # Linear Decay
            exploration_rate = self.initial_exploration_rate - (
                        self.initial_exploration_rate - self.min_exploration_rate) * (episode / self.max_episodes)
        elif self.current_decay_function == 3:  # Polynomial Decay
            exploration_rate = self.initial_exploration_rate * (1 - episode / self.max_episodes) ** 2
        elif self.current_decay_function == 4:  # Inverse Time Decay
            exploration_rate = self.initial_exploration_rate / (1 + episode)
        elif self.current_decay_function == 5:  # Sine Wave Decay
            exploration_rate = self.min_exploration_rate + 0.5 * (
                        self.initial_exploration_rate - self.min_exploration_rate) * (
                                           1 + np.sin(np.pi * episode / self.max_episodes))
        elif self.current_decay_function == 6:  # Logarithmic Decay
            exploration_rate = self.initial_exploration_rate - (
                        self.initial_exploration_rate - self.min_exploration_rate) * np.log(episode + 1) / np.log(
                self.max_episodes + 1)
        elif self.current_decay_function == 7:  # Hyperbolic Tangent Decay
            exploration_rate = self.min_exploration_rate + 0.5 * (
                        self.initial_exploration_rate - self.min_exploration_rate) * (
                                           1 - np.tanh(episode / self.max_episodes))
        elif self.current_decay_function == 8:  # Square Root Decay
            exploration_rate = self.initial_exploration_rate * (1 - np.sqrt(episode / self.max_episodes))
        elif self.current_decay_function == 9:  # Stepwise Decay
            steps = 10
            step_size = (self.initial_exploration_rate - self.min_exploration_rate) / steps
            exploration_rate = self.initial_exploration_rate - (episode // (self.max_episodes // steps)) * step_size
        elif self.current_decay_function == 10:  # Inverse Square Root Decay
            exploration_rate = self.initial_exploration_rate / np.sqrt(episode + 1)
        elif self.current_decay_function == 11:  # Sigmoid Decay
            midpoint = self.max_episodes / 2
            smoothness = self.max_episodes / 10  # Adjust this divisor to change smoothness
            exploration_rate = self.min_exploration_rate + (
                    self.initial_exploration_rate - self.min_exploration_rate) / (
                                       1 + np.exp((episode - midpoint) / smoothness))
        elif self.current_decay_function == 12:  # Quadratic Decay
            exploration_rate = self.initial_exploration_rate * (1 - (episode / self.max_episodes) ** 2)
        elif self.current_decay_function == 13:  # Cubic Decay
            exploration_rate = self.initial_exploration_rate * (1 - (episode / self.max_episodes) ** 3)
        elif self.current_decay_function == 14:  # Sine Squared Decay
            exploration_rate = self.min_exploration_rate + (
                        self.initial_exploration_rate - self.min_exploration_rate) * np.sin(
                np.pi * episode / self.max_episodes) ** 2
        elif self.current_decay_function == 15:  # Cosine Squared Decay
            exploration_rate = self.min_exploration_rate + (
                        self.initial_exploration_rate - self.min_exploration_rate) * np.cos(
                np.pi * episode / self.max_episodes) ** 2
        elif self.current_decay_function == 16:  # Double Exponential Decay
            exploration_rate = self.initial_exploration_rate * np.exp(-np.exp(episode / self.max_episodes))
        elif self.current_decay_function == 17:  # Log-Logistic Decay
            exploration_rate = self.min_exploration_rate + (
                        self.initial_exploration_rate - self.min_exploration_rate) / (1 + np.log(episode + 1))
        elif self.current_decay_function == 18:  # Harmonic Series Decay
            exploration_rate = self.min_exploration_rate + (
                        self.initial_exploration_rate - self.min_exploration_rate) / (
                                           1 + np.sum(1 / np.arange(1, episode + 2)))
        elif self.current_decay_function == 19:  # Piecewise Linear Decay
            if episode < self.max_episodes / 2:
                exploration_rate = self.initial_exploration_rate - (
                            self.initial_exploration_rate - self.min_exploration_rate) * (
                                               2 * episode / self.max_episodes)
            else:
                exploration_rate = self.min_exploration_rate
        elif self.current_decay_function == 20:  # Custom Polynomial Decay
            p = 3  # Change the power for different polynomial behaviors
            exploration_rate = self.initial_exploration_rate * (1 - (episode / self.max_episodes) ** p)
        else:
            raise ValueError("Invalid decay function number")

        return exploration_rate


class ActorCriticNetwork(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super(ActorCriticNetwork, self).__init__()
        self.shared_layers = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )
        self.actor = nn.Sequential(
            nn.Linear(hidden_dim, output_dim),
            nn.Softmax(dim=-1)
        )
        self.critic = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        shared_output = self.shared_layers(x)
        action_probs = self.actor(shared_output)
        state_value = self.critic(shared_output)
        return action_probs, state_value


class PPOCustomAgent:
    def __init__(self, env, run_name, shared_config_path, agent_config_path=None, override_config=None):
        # Load Shared Config
        self.shared_config = load_config(shared_config_path)

        # Load Agent Specific Config if path provided
        if agent_config_path:
            self.agent_config = load_config(agent_config_path)
        else:
            self.agent_config = {}

        # If override_config is provided, merge it with the loaded agent_config
        if override_config:
            self.agent_config.update(override_config)

        # Access the results directory from the shared_config
        self.results_directory = self.shared_config['directories']['results_directory']

        # Create a unique subdirectory for each run to avoid overwriting results
        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.agent_type = "ppo_custom"
        self.run_name = run_name
        self.results_subdirectory = os.path.join(self.results_directory, self.agent_type, self.run_name, self.timestamp)
        if not os.path.exists(self.results_subdirectory):
            os.makedirs(self.results_subdirectory, exist_ok=True)
        self.model_directory = self.shared_config['directories']['model_directory']
        self.model_subdirectory = os.path.join(self.model_directory, self.agent_type, self.run_name, self.timestamp)
        if not os.path.exists(self.model_subdirectory):
            os.makedirs(self.model_subdirectory, exist_ok=True)

        # Set up logging to the correct directory
        log_file_path = os.path.join(self.results_subdirectory, 'agent_log.txt')
        logging.basicConfig(filename=log_file_path, level=logging.INFO)

        # Initialize wandb
        wandb.init(project=self.agent_type, name=self.run_name)

        # Initialize the neural network
        self.input_dim = len(env.reset()[0])
        self.output_dim = env.action_space.nvec[0]
        self.hidden_dim = self.agent_config['agent']['hidden_units']

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = ActorCriticNetwork(self.input_dim, self.hidden_dim, self.output_dim)
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.agent_config['agent']['learning_rate'])

        # Initialize agent-specific configurations and variables
        self.env = env
        self.max_episodes = self.agent_config['agent']['max_episodes']
        self.discount_factor = self.agent_config['agent']['discount_factor']
        self.exploration_rate = self.agent_config['agent']['exploration_rate']
        self.min_exploration_rate = self.agent_config['agent']['min_exploration_rate']
        self.exploration_decay_rate = self.agent_config['agent']['exploration_decay_rate']
        self.target_network_frequency = self.agent_config['agent']['target_network_frequency']

        # PPO-specific parameters
        self.clip_epsilon = self.agent_config['agent']['clip_epsilon']
        self.epochs = self.agent_config['agent']['epochs']
        self.batch_size = self.agent_config['agent']['batch_size']

        self.possible_actions = [list(range(0, (k))) for k in self.env.action_space.nvec]
        self.all_actions = [str(i) for i in list(itertools.product(*self.possible_actions))]

        # moving average for early stopping criteria
        self.moving_average_window = 100  # Number of episodes to consider for moving average
        self.stopping_criterion = 0.01  # Threshold for stopping
        self.prev_moving_avg = -float(
            'inf')  # Initialize to negative infinity to ensure any reward is considered an improvement in the first episode.

        # Hidden State
        self.hidden_state = None
        self.reward_window = deque(maxlen=self.moving_average_window)
        # Initialize the learning rate scheduler
        self.scheduler = StepLR(self.optimizer, step_size=100, gamma=0.9)
        self.learning_rate_decay = self.agent_config['agent']['learning_rate_decay']

        self.softmax_temperature = self.agent_config['agent']['softmax_temperature']

        self.state_visit_counts = {}

        self.decay_handler = ExplorationRateDecay(self.max_episodes, self.min_exploration_rate, self.exploration_rate)
        self.decay_function = self.agent_config['agent']['e_decay_function']

    def select_action(self, state):
        state = torch.FloatTensor(state).unsqueeze(0)
        with torch.no_grad():
            action_probs, _ = self.model(state)

        # Check for NaN or Inf values
        if torch.any(torch.isnan(action_probs)) or torch.any(torch.isinf(action_probs)):
            print(f"NaN or Inf detected in action_probs: {action_probs}")
            # Handle this case, perhaps by returning a random action
            action = random.randint(0, self.output_dim - 1)
            return action, torch.tensor(float('-inf'))  # Return a very low log probability

        action = torch.multinomial(action_probs, 1).item()
        log_prob = torch.log(action_probs[0, action])
        return action, log_prob

    def compute_gae(self, rewards, values, dones, next_value):
        advantages = []
        gae = 0
        values = values + [next_value]
        for i in reversed(range(len(rewards))):
            delta = rewards[i] + self.discount_factor * values[i + 1] * (1 - dones[i]) - values[i]
            gae = delta + self.discount_factor * self.agent_config['agent']['gae_lambda'] * (1 - dones[i]) * gae
            advantages.insert(0, gae)
        return advantages

    def ppo_update(self, states, actions, old_log_probs, advantages, returns):
        for _ in range(self.epochs):
            for start in range(0, len(states), self.batch_size):
                end = start + self.batch_size
                batch_states = states[start:end]
                batch_actions = actions[start:end]
                batch_old_log_probs = old_log_probs[start:end]
                batch_advantages = advantages[start:end]
                batch_returns = returns[start:end]

                action_probs, state_values = self.model(batch_states)
                dist = Categorical(action_probs)
                new_log_probs = dist.log_prob(batch_actions)

                ratio = (new_log_probs - batch_old_log_probs).exp()
                surr1 = ratio * batch_advantages
                surr2 = torch.clamp(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon) * batch_advantages

                actor_loss = -torch.min(surr1, surr2).mean()
                critic_loss = F.mse_loss(state_values.squeeze(), batch_returns)
                entropy = dist.entropy().mean()

                loss = actor_loss + 0.5 * critic_loss - 0.01 * entropy

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=0.5)
                self.optimizer.step()

        # self.scheduler.step()
        return loss

    def train(self, alpha):
        pbar = tqdm(total=self.max_episodes, desc="Training Progress", leave=True)

        actual_rewards = []
        explained_variance_per_episode = []
        visited_state_counts = {}

        for episode in range(self.max_episodes):
            self.decay_handler.set_decay_function(self.decay_function)
            state, _ = self.env.reset()
            state = np.array(state, dtype=np.float32)
            episode_reward = 0
            done = False

            states, actions, log_probs, rewards, values, dones = [], [], [], [], [], []

            while not done:
                action, log_prob = self.select_action(state)
                next_state, reward, done, _, _ = self.env.step(([action * 50], alpha))

                # Update visited state count
                state_tuple = tuple(state)
                visited_state_counts[state_tuple] = visited_state_counts.get(state_tuple, 0) + 1

                states.append(state)
                actions.append(action)
                log_probs.append(log_prob)
                rewards.append(reward)
                values.append(self.model(torch.FloatTensor(state).unsqueeze(0))[1].item())
                dones.append(done)

                state = next_state
                episode_reward += reward

            # Compute advantages and returns
            next_value = self.model(torch.FloatTensor(state).unsqueeze(0))[1].item()
            advantages = self.compute_gae(rewards, values, dones, next_value)
            returns = [adv + val for adv, val in zip(advantages, values)]

            # Convert to tensors
            states = torch.FloatTensor(np.array(states))
            actions = torch.LongTensor(actions)
            old_log_probs = torch.stack(log_probs).detach()
            advantages = torch.FloatTensor(advantages)
            returns = torch.FloatTensor(returns)

            # PPO Update
            loss = self.ppo_update(states, actions, old_log_probs, advantages, returns)

            actual_rewards.append(rewards)

            if returns.numel() > 0:
                explained_variance = self.calculate_explained_variance(rewards, returns.cpu().detach().numpy().tolist())
            else:
                explained_variance = 0
            explained_variance_per_episode.append(explained_variance)

            self.exploration_rate = self.decay_handler.get_exploration_rate(episode)

            wandb.log({
                "episode": episode,
                "episode_reward": episode_reward,
                "exploration_rate": self.exploration_rate,
                "loss": loss.item() if loss is not None else 0,
                "avg_episode_reward": np.mean(rewards),
                "explained_variance": explained_variance,
            })

            pbar.update(1)
            pbar.set_description(f"Reward: {episode_reward:.2f}, Epsilon: {self.exploration_rate:.2f}")

        pbar.close()

        # After training, save the model
        model_file_path = os.path.join(self.model_subdirectory, 'model.pt')
        torch.save(self.model.state_dict(), model_file_path)

        # Visualization and logging
        self.visualize_and_log_results(actual_rewards, explained_variance_per_episode, visited_state_counts, alpha)

        return self.model

    def visualize_and_log_results(self, actual_rewards, explained_variance_per_episode, visited_state_counts, alpha):
        saved_model = load_saved_model(self.model_directory, self.agent_type, self.run_name, self.timestamp,
                                       self.input_dim, self.hidden_dim, self.output_dim)
        value_range = range(0, 101, 10)
        all_states = [np.array([i, j]) for i in value_range for j in value_range]
        all_states_path = visualize_all_states(saved_model, all_states, self.run_name, self.max_episodes, alpha,
                                               self.results_subdirectory)
        wandb.log({"All_States_Visualization": [wandb.Image(all_states_path)]})

        avg_rewards = [np.mean(rewards) for rewards in actual_rewards]
        explained_variance_path = os.path.join(self.results_subdirectory, 'explained_variance.png')
        visualize_explained_variance(explained_variance_per_episode, explained_variance_path)
        wandb.log({"Explained Variance": [wandb.Image(explained_variance_path)]})

        # Visualize visited states
        states = list(visited_state_counts.keys())
        visit_counts = list(visited_state_counts.values())
        states_visited_path = states_visited_viz(states, visit_counts, alpha, self.results_subdirectory)
        wandb.log({"States Visited": [wandb.Image(states_visited_path)]})

    def calculate_explained_variance(self, y_true, y_pred):
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)

        if len(y_true) != len(y_pred):
            min_length = min(len(y_true), len(y_pred))
            y_true = y_true[:min_length]
            y_pred = y_pred[:min_length]

        var_y = np.var(y_true)
        return np.mean(1 - np.var(y_true - y_pred) / var_y) if var_y != 0 else 0.0

    def train_single_run(self, alpha, seed):
        set_seed(seed)
        # self.replay_memory = deque(maxlen=self.agent_config['agent']['replay_memory_capacity'])
        self.reward_window = deque(maxlen=self.moving_average_window)
        self.model = ActorCriticNetwork(self.input_dim, self.hidden_dim, self.output_dim).to(self.device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.agent_config['agent']['learning_rate'])
        self.scheduler = StepLR(self.optimizer, step_size=100, gamma=self.learning_rate_decay)

        self.run_rewards_per_episode = []  # Store rewards per episode for this run

        pbar = tqdm(total=self.max_episodes, desc=f"Training Run {seed}", leave=True)
        visited_state_counts = {}

        for episode in range(self.max_episodes):
            self.decay_handler.set_decay_function(self.decay_function)
            state, _ = self.env.reset()
            state = np.array(state, dtype=np.float32)
            total_reward = 0
            done = False
            episode_rewards = []
            visited_states = []
            rewards = []
            loss = torch.tensor(0.0)  # Initialize loss here
            while not done:
                action = self.select_action(state)
                next_state, reward, done, _, _ = self.env.step(([action * 50], alpha))
                next_state = np.array(next_state, dtype=np.float32)

                # self.replay_memory.append((state, action, reward, next_state, done))
                state = next_state
                total_reward += reward
                episode_rewards.append(reward)

                state_tuple = tuple(state)
                visited_states.append(state_tuple)
                visited_state_counts[state_tuple] = visited_state_counts.get(state_tuple, 0) + 1

            self.run_rewards_per_episode.append(rewards)
            self.exploration_rate = self.decay_handler.get_exploration_rate(episode)

            pbar.update(1)
            pbar.set_description(
                f"Loss:{loss}, Total Reward: {total_reward:.2f}, Epsilon: {self.exploration_rate:.2f}")

        pbar.close()

        return self.run_rewards_per_episode

    def compute_tolerance_interval(self, data, alpha, beta):
        n = len(data)
        if n == 0:
            return np.nan, np.nan  # Handle case with no data

        sorted_data = np.sort(data)
        nu = stats.binom.ppf(1 - alpha, n, beta)
        nu = int(nu)

        if nu >= n:
            return sorted_data[0], sorted_data[-1]  # If nu is greater than available data points, return full range

        l = int(np.floor(nu / 2))
        u = int(np.ceil(n - nu / 2))

        return sorted_data[l], sorted_data[u]

    def visualize_tolerance_interval_curve(self, returns_per_episode, alpha, beta, output_path, metric='mean'):
        num_episodes = len(returns_per_episode[0])
        lower_bounds = []
        upper_bounds = []
        central_tendency = []
        episodes = list(range(num_episodes))  # Assume all runs have the same number of episodes)

        for episode in episodes:
            returns_at_episode = [returns[episode] for returns in
                                  returns_per_episode]  # Shape: (num_runs, episode_length)
            returns_at_episode = [item for sublist in returns_at_episode for item in sublist]  # Flatten to 1D

            if metric == 'mean':
                performance = np.mean(returns_at_episode)
            elif metric == 'median':
                performance = np.median(returns_at_episode)
            else:
                raise ValueError("Invalid metric specified. Use 'mean' or 'median'.")

            central_tendency.append(performance)
            lower, upper = self.compute_tolerance_interval(returns_at_episode, alpha, beta)
            lower_bounds.append(lower)
            upper_bounds.append(upper)

        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)
        central_tendency = np.array(central_tendency)

        # Smoothing the curve
        spline_points = 300  # Number of points for spline interpolation
        episodes_smooth = np.linspace(episodes[0], episodes[-1], spline_points)
        central_tendency_smooth = make_interp_spline(episodes, central_tendency)(episodes_smooth)
        lower_bounds_smooth = make_interp_spline(episodes, lower_bounds)(episodes_smooth)
        upper_bounds_smooth = make_interp_spline(episodes, upper_bounds)(episodes_smooth)

        plt.figure(figsize=(10, 6))
        sns.set_style("whitegrid")

        # Plot central tendency
        sns.lineplot(x=episodes_smooth, y=central_tendency_smooth, color='blue',
                     label=f'{metric.capitalize()} Performance')

        # Fill between for tolerance interval
        plt.fill_between(episodes_smooth, lower_bounds_smooth, upper_bounds_smooth, color='lightblue', alpha=0.2,
                         label=f'Tolerance Interval (α={alpha}, β={beta})')

        plt.title(f'Tolerance Interval Curve for {metric.capitalize()} Performance')
        plt.xlabel('Episode')
        plt.ylabel('Return')
        plt.legend()
        plt.savefig(output_path)
        plt.close()

    def compute_confidence_interval(self, data, alpha):
        n = len(data)
        mean = np.mean(data)
        std_err = np.std(data, ddof=1) / np.sqrt(n)
        t_value = stats.t.ppf(1 - alpha / 2, df=n - 1)
        margin_of_error = t_value * std_err
        return mean - margin_of_error, mean + margin_of_error

    def visualize_confidence_interval(self, returns, alpha, output_path):
        means = []
        lower_bounds = []
        upper_bounds = []
        episodes = list(range(len(returns[0])))  # Assume all runs have the same number of episodes

        for episode in episodes:
            episode_returns = [returns[run][episode] for run in range(len(returns))]
            mean = np.mean(episode_returns)
            lower, upper = self.compute_confidence_interval(episode_returns, alpha)
            means.append(mean)
            lower_bounds.append(lower)
            upper_bounds.append(upper)

        means = np.array(means)
        lower_bounds = np.array(lower_bounds)
        upper_bounds = np.array(upper_bounds)

        # Smoothing the curve
        spline_points = 300  # Number of points for spline interpolation
        episodes_smooth = np.linspace(episodes[0], episodes[-1], spline_points)
        means_smooth = make_interp_spline(episodes, means)(episodes_smooth)
        lower_bounds_smooth = make_interp_spline(episodes, lower_bounds)(episodes_smooth)
        upper_bounds_smooth = make_interp_spline(episodes, upper_bounds)(episodes_smooth)

        plt.figure(figsize=(10, 6))
        sns.set_style("whitegrid")

        # Plot mean performance
        sns.lineplot(x=episodes_smooth, y=means_smooth, label='Mean Performance', color='blue')

        # Fill between for confidence interval
        plt.fill_between(episodes_smooth, lower_bounds_smooth, upper_bounds_smooth, color='lightblue', alpha=0.2,
                         label=f'Confidence Interval (α={alpha})')

        plt.title(f'Confidence Interval Curve for Mean Performance')
        plt.xlabel('Episode')
        plt.ylabel('Return')
        plt.legend()
        plt.savefig(output_path)
        plt.close()

    def visualize_boxplot_confidence_interval(self, returns, alpha, output_path):
        episodes = list(range(len(returns[0])))  # Assume all runs have the same number of episodes
        returns_transposed = np.array(returns).T.tolist()  # Transpose to get returns per episode

        plt.figure(figsize=(12, 8))
        sns.boxplot(data=returns_transposed, whis=[100 * alpha / 2, 100 * (1 - alpha / 2)], color='lightblue')
        plt.title(f'Box Plot of Returns with Confidence Interval (α={alpha})')
        plt.xlabel('Episode')
        plt.ylabel('Return')
        plt.xticks(ticks=range(len(episodes)), labels=episodes)
        plt.savefig(output_path)
        plt.close()

    def multiple_runs(self, num_runs, alpha_t, beta_t):
        returns_per_episode = []

        for run in range(num_runs):
            returns = self.train_single_run(run, alpha_t)
            returns_per_episode.append(returns)

        returns_per_episode = np.array(returns_per_episode)  # Shape: (num_runs, max_episodes, episode_length)

        output_path_mean = os.path.join(self.results_subdirectory, 'tolerance_interval_mean.png')
        output_path_median = os.path.join(self.results_subdirectory, 'tolerance_interval_median.png')

        self.visualize_tolerance_interval_curve(returns_per_episode, alpha_t, beta_t, output_path_mean, 'mean')
        self.visualize_tolerance_interval_curve(returns_per_episode, alpha_t, beta_t, output_path_median, 'median')

        wandb.log({"Tolerance Interval Mean": [wandb.Image(output_path_mean)]})
        wandb.log({"Tolerance Interval Median": [wandb.Image(output_path_median)]})

        # Confidence Intervals
        confidence_alpha = 0.05  # 95% confidence interval
        confidence_output_path = os.path.join(self.results_subdirectory, 'confidence_interval.png')
        self.visualize_confidence_interval(returns_per_episode, confidence_alpha, confidence_output_path)
        wandb.log({"Confidence Interval": [wandb.Image(confidence_output_path)]})

        # Box Plot Confidence Intervals
        boxplot_output_path = os.path.join(self.results_subdirectory, 'boxplot_confidence_interval.png')
        self.visualize_boxplot_confidence_interval(returns_per_episode, confidence_alpha, boxplot_output_path)
        wandb.log({"Box Plot Confidence Interval": [wandb.Image(boxplot_output_path)]})

def load_saved_model(model_directory, agent_type, run_name, timestamp, input_dim, hidden_dim, action_space_nvec):
    model_subdirectory = os.path.join(model_directory, agent_type, run_name, timestamp)
    model_file_path = os.path.join(model_subdirectory, 'model.pt')

    if not os.path.exists(model_file_path):
        print(f"Model file not found in {model_file_path}")
        return None

    model = ActorCriticNetwork(input_dim, hidden_dim, action_space_nvec)
    model.load_state_dict(torch.load(model_file_path))
    model.eval()  # Set the model to evaluation mode

    return model

def calculate_explained_variance(actual_rewards, predicted_rewards):
    actual_rewards = np.array(actual_rewards)
    predicted_rewards = np.array(predicted_rewards)
    variance_actual = np.var(actual_rewards, ddof=1)
    variance_unexplained = np.var(actual_rewards - predicted_rewards, ddof=1)
    explained_variance = 1 - (variance_unexplained / variance_actual)
    return explained_variance

def visualize_explained_variance(explained_variance_per_episode, output_path):
    plt.figure(figsize=(10, 6))
    plt.plot(explained_variance_per_episode, label='Explained Variance')
    plt.xlabel('Episode')
    plt.ylabel('Explained Variance')
    plt.title('Explained Variance over Episodes')
    plt.legend()
    plt.grid(True)
    plt.savefig(output_path)
    plt.close()


# import torch
# import torch.nn as nn
# import torch.optim as optim
# import numpy as np
# import os
# from datetime import datetime
# import logging
# from collections import deque
# import random
# import itertools
# from tqdm import tqdm
# from .utilities import load_config
# from .visualizer import visualize_all_states, visualize_q_table, visualize_variance_in_rewards_heatmap, \
#     visualize_explained_variance, visualize_variance_in_rewards, visualize_infected_vs_community_risk_table, states_visited_viz
# import wandb
# import math
# import torch.nn.functional as F
# from torch.optim.lr_scheduler import StepLR
#
# from scipy import stats
# import seaborn as sns
# import matplotlib.pyplot as plt
#
# class ExplorationRateDecay:
#     def __init__(self, max_episodes, min_exploration_rate, initial_exploration_rate):
#         self.max_episodes = max_episodes
#         self.min_exploration_rate = min_exploration_rate
#         self.initial_exploration_rate = initial_exploration_rate
#         self.current_decay_function = 1  # Variable to switch between different decay functions
#
#     def set_decay_function(self, decay_function_number):
#         self.current_decay_function = decay_function_number
#
#     def get_exploration_rate(self, episode):
#         if self.current_decay_function == 1:  # Exponential Decay
#             exploration_rate = self.initial_exploration_rate * np.exp(-episode / self.max_episodes)
#         elif self.current_decay_function == 2:  # Linear Decay
#             exploration_rate = self.initial_exploration_rate - (
#                         self.initial_exploration_rate - self.min_exploration_rate) * (episode / self.max_episodes)
#         elif self.current_decay_function == 3:  # Polynomial Decay
#             exploration_rate = self.initial_exploration_rate * (1 - episode / self.max_episodes) ** 2
#         elif self.current_decay_function == 4:  # Inverse Time Decay
#             exploration_rate = self.initial_exploration_rate / (1 + episode)
#         elif self.current_decay_function == 5:  # Sine Wave Decay
#             exploration_rate = self.min_exploration_rate + 0.5 * (
#                         self.initial_exploration_rate - self.min_exploration_rate) * (
#                                            1 + np.sin(np.pi * episode / self.max_episodes))
#         elif self.current_decay_function == 6:  # Logarithmic Decay
#             exploration_rate = self.initial_exploration_rate - (
#                         self.initial_exploration_rate - self.min_exploration_rate) * np.log(episode + 1) / np.log(
#                 self.max_episodes + 1)
#         elif self.current_decay_function == 7:  # Hyperbolic Tangent Decay
#             exploration_rate = self.min_exploration_rate + 0.5 * (
#                         self.initial_exploration_rate - self.min_exploration_rate) * (
#                                            1 - np.tanh(episode / self.max_episodes))
#         elif self.current_decay_function == 8:  # Square Root Decay
#             exploration_rate = self.initial_exploration_rate * (1 - np.sqrt(episode / self.max_episodes))
#         elif self.current_decay_function == 9:  # Stepwise Decay
#             steps = 10
#             step_size = (self.initial_exploration_rate - self.min_exploration_rate) / steps
#             exploration_rate = self.initial_exploration_rate - (episode // (self.max_episodes // steps)) * step_size
#         elif self.current_decay_function == 10:  # Inverse Square Root Decay
#             exploration_rate = self.initial_exploration_rate / np.sqrt(episode + 1)
#         elif self.current_decay_function == 11:  # Sigmoid Decay
#             exploration_rate = self.min_exploration_rate + (
#                         self.initial_exploration_rate - self.min_exploration_rate) / (
#                                            1 + np.exp(episode - self.max_episodes / 2))
#         elif self.current_decay_function == 12:  # Quadratic Decay
#             exploration_rate = self.initial_exploration_rate * (1 - (episode / self.max_episodes) ** 2)
#         elif self.current_decay_function == 13:  # Cubic Decay
#             exploration_rate = self.initial_exploration_rate * (1 - (episode / self.max_episodes) ** 3)
#         elif self.current_decay_function == 14:  # Sine Squared Decay
#             exploration_rate = self.min_exploration_rate + (
#                         self.initial_exploration_rate - self.min_exploration_rate) * np.sin(
#                 np.pi * episode / self.max_episodes) ** 2
#         elif self.current_decay_function == 15:  # Cosine Squared Decay
#             exploration_rate = self.min_exploration_rate + (
#                         self.initial_exploration_rate - self.min_exploration_rate) * np.cos(
#                 np.pi * episode / self.max_episodes) ** 2
#         elif self.current_decay_function == 16:  # Double Exponential Decay
#             exploration_rate = self.initial_exploration_rate * np.exp(-np.exp(episode / self.max_episodes))
#         elif self.current_decay_function == 17:  # Log-Logistic Decay
#             exploration_rate = self.min_exploration_rate + (
#                         self.initial_exploration_rate - self.min_exploration_rate) / (1 + np.log(episode + 1))
#         elif self.current_decay_function == 18:  # Harmonic Series Decay
#             exploration_rate = self.min_exploration_rate + (
#                         self.initial_exploration_rate - self.min_exploration_rate) / (
#                                            1 + np.sum(1 / np.arange(1, episode + 2)))
#         elif self.current_decay_function == 19:  # Piecewise Linear Decay
#             if episode < self.max_episodes / 2:
#                 exploration_rate = self.initial_exploration_rate - (
#                             self.initial_exploration_rate - self.min_exploration_rate) * (
#                                                2 * episode / self.max_episodes)
#             else:
#                 exploration_rate = self.min_exploration_rate
#         elif self.current_decay_function == 20:  # Custom Polynomial Decay
#             p = 3  # Change the power for different polynomial behaviors
#             exploration_rate = self.initial_exploration_rate * (1 - (episode / self.max_episodes) ** p)
#         else:
#             raise ValueError("Invalid decay function number")
#
#         return exploration_rate
# def compute_tolerance_interval(self, data, alpha, beta):
#     """
#     Compute the (alpha, beta)-tolerance interval for a given data sample.
#
#     Parameters:
#     data (list or numpy array): The data sample.
#     alpha (float): The nominal error rate (e.g., 0.05 for 95%).
#     beta (float): The proportion of future samples to be captured (e.g., 0.9 for 90%).
#
#     Returns:
#     (float, float): The lower and upper bounds of the tolerance interval.
#     """
#     n = len(data)
#     sorted_data = np.sort(data)
#
#     # Compute the number of samples that do not belong to the middle beta proportion
#     nu = stats.binom.ppf(1 - alpha, n, beta)
#
#     # Compute the indices for the lower and upper bounds
#     l = int(np.floor(nu / 2))
#     u = int(np.ceil(n - nu / 2))
#
#     return sorted_data[l], sorted_data[u]
#
# def set_seed(seed):
#     random.seed(seed)
#     np.random.seed(seed)
#     torch.manual_seed(seed)
#     if torch.cuda.is_available():
#         torch.cuda.manual_seed(seed)
#         torch.cuda.manual_seed_all(seed)
#     torch.backends.cudnn.deterministic = True
#     torch.backends.cudnn.benchmark = False
#
# # Set seed for reproducibility
# set_seed(100)  # Replace 42 with your desired seed value
#
# class ActorCriticNetwork(nn.Module):
#     def __init__(self, input_dim, hidden_dim, out_dim):
#         super(ActorCriticNetwork, self).__init__()
#         self.encoder = nn.Sequential(
#             nn.Linear(input_dim, hidden_dim),
#             nn.ReLU(),
#             nn.Linear(hidden_dim, hidden_dim),
#             nn.ReLU(),
#             nn.Linear(hidden_dim, hidden_dim),
#             nn.ReLU()
#         )
#
#         self.actor = nn.Sequential(
#             nn.Linear(hidden_dim, out_dim),
#             nn.Softmax(dim=-1)
#         )
#
#         self.critic = nn.Linear(hidden_dim, 1)
#
#     def forward(self, x):
#         shared_output = self.encoder(x)
#         policy_dist = self.actor(shared_output)
#         value = self.critic(shared_output)
#         return policy_dist, value
#
#
# class PPOCustomAgent:
#     def __init__(self, env, run_name, shared_config_path, agent_config_path=None, override_config=None):
#         # Load Shared Config
#         self.shared_config = load_config(shared_config_path)
#
#         # Load Agent Specific Config if path provided
#         if agent_config_path:
#             self.agent_config = load_config(agent_config_path)
#         else:
#             self.agent_config = {}
#
#         # If override_config is provided, merge it with the loaded agent_config
#         if override_config:
#             self.agent_config.update(override_config)
#
#         # Access the results directory from the shared_config
#         self.results_directory = self.shared_config['directories']['results_directory']
#
#         # Create a unique subdirectory for each run to avoid overwriting results
#         self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
#         self.agent_type = "ppo_custom"
#         self.run_name = run_name
#         self.results_subdirectory = os.path.join(self.results_directory, self.agent_type, self.run_name, self.timestamp)
#         if not os.path.exists(self.results_subdirectory):
#             os.makedirs(self.results_subdirectory, exist_ok=True)
#         self.model_directory = self.shared_config['directories']['model_directory']
#         self.model_subdirectory = os.path.join(self.model_directory, self.agent_type, self.run_name, self.timestamp)
#         if not os.path.exists(self.model_subdirectory):
#             os.makedirs(self.model_subdirectory, exist_ok=True)
#
#         # Set up logging to the correct directory
#         log_file_path = os.path.join(self.results_subdirectory, 'agent_log.txt')
#         logging.basicConfig(filename=log_file_path, level=logging.INFO)
#
#         # Initialize wandb
#         wandb.init(project=self.agent_type, name=self.run_name)
#
#         # Initialize the neural network
#         self.input_dim = len(env.reset()[0])
#         self.output_dim = env.action_space.nvec[0]
#         self.hidden_dim = self.agent_config['agent']['hidden_units']
#         self.model = ActorCriticNetwork(self.input_dim, self.hidden_dim, self.output_dim)
#         self.optimizer = optim.Adam(self.model.parameters(), lr=self.agent_config['agent']['learning_rate'])
#
#         # Initialize agent-specific configurations and variables
#         self.env = env
#         self.max_episodes = self.agent_config['agent']['max_episodes']
#         self.discount_factor = self.agent_config['agent']['discount_factor']
#         self.epsilon = self.agent_config['agent']['epsilon']  # Clipping parameter for PPO
#         self.lmbda = self.agent_config['agent']['lambda']  # GAE parameter
#         self.min_exploration_rate = self.agent_config['agent']['min_exploration_rate']
#         self.exploration_rate = self.agent_config['agent']['exploration_rate']
#
#         # Replay memory
#         self.replay_memory = deque(maxlen=self.agent_config['agent']['replay_memory_capacity'])
#         self.batch_size = self.agent_config['agent']['batch_size']
#
#         self.possible_actions = [list(range(0, (k))) for k in self.env.action_space.nvec]
#         self.all_actions = [str(i) for i in list(itertools.product(*self.possible_actions))]
#
#         # moving average for early stopping criteria
#         self.moving_average_window = 100  # Number of episodes to consider for moving average
#         self.stopping_criterion = 0.01  # Threshold for stopping
#         self.prev_moving_avg = -float('inf')  # Initialize to negative infinity to ensure any reward is considered an improvement in the first episode.
#
#         # Hidden State
#         self.hidden_state = None
#         self.reward_window = deque(maxlen=self.moving_average_window)
#         self.scheduler = StepLR(self.optimizer, step_size=2, gamma=0.9)
#
#         self.decay_handler = ExplorationRateDecay(self.max_episodes, self.min_exploration_rate, self.exploration_rate)
#         self.decay_function = self.agent_config['agent']['e_decay_function']
#
#
#     def update_replay_memory(self, state, action, reward, next_state, done, log_prob, value):
#         # Convert to appropriate types before appending to replay memory
#         state = np.array(state, dtype=np.float32)
#         next_state = np.array(next_state, dtype=np.float32)
#         action = int(action)
#         reward = float(reward)
#         done = bool(done)
#         self.replay_memory.append((state, action, reward, next_state, done, log_prob, value))
#
#     def compute_advantages(self, rewards, values, dones):
#         advantages = []
#         returns = []
#         advantage = 0
#         for i in reversed(range(len(rewards))):
#             if i == len(rewards) - 1:
#                 next_value = values[i + 1] if i + 1 < len(values) else values[i]
#             else:
#                 next_value = values[i + 1]
#
#             td_error = rewards[i] + self.discount_factor * next_value * (1 - dones[i]) - values[i]
#             advantage = td_error + self.discount_factor * self.lmbda * (1 - dones[i]) * advantage
#             advantages.insert(0, advantage)
#             returns.insert(0, advantage + values[i])
#
#         return torch.FloatTensor(advantages), torch.FloatTensor(returns)
#
#     def train(self, alpha):
#         pbar = tqdm(total=self.max_episodes, desc="Training Progress", leave=True)
#
#         # Initialize accumulators for visualization
#         actual_rewards = []
#         predicted_rewards = []
#         rewards_per_episode = []
#         visited_state_counts = {}
#
#         # Set up learning rate scheduler
#         scheduler = StepLR(self.optimizer, step_size=100, gamma=0.9)
#
#         for episode in range(self.max_episodes):
#             state, _ = self.env.reset()
#             state = torch.FloatTensor(state)
#             self.decay_handler.set_decay_function(self.decay_function)
#             terminated = False
#
#             episode_rewards = []
#             episode_log_probs = []
#             episode_values = []
#             episode_dones = []
#             visited_states = []  # List to store visited states
#
#             while not terminated:
#                 policy_dist, value = self.model(state)
#
#                 # Check for NaN or Inf values immediately
#                 if torch.any(torch.isnan(policy_dist)) or torch.any(torch.isinf(policy_dist)):
#                     print(f"NaN or Inf detected in policy_dist at episode {episode}")
#                     print(f"policy_dist: {policy_dist}")
#                     print(f"value: {value}")
#                     raise ValueError("policy_dist contains NaN or Inf values")
#
#                 # Clamp policy_dist to ensure all elements are within valid range
#                 policy_dist = torch.clamp(policy_dist, min=1e-9, max=1.0 - 1e-9)
#
#                 # Normalize policy_dist to ensure it sums to 1
#                 policy_dist = policy_dist / policy_dist.sum()
#
#                 action = torch.multinomial(policy_dist, 1).item()
#                 log_prob = torch.log(policy_dist[action] + 1e-9)  # Add epsilon to avoid log(0)
#                 next_state, reward, terminated, _, info = self.env.step(([action * 50], alpha))
#                 episode_rewards.append(reward)
#                 episode_log_probs.append(log_prob)  # Do not detach yet
#                 episode_values.append(value)  # Do not detach yet
#                 episode_dones.append(terminated)
#
#                 visited_states.append(state.tolist())  # Add the current state to the list of visited states
#
#                 # Update state visitation count
#                 state_tuple = tuple(state.numpy())  # Convert tensor to tuple for hashing
#                 visited_state_counts[state_tuple] = visited_state_counts.get(state_tuple, 0) + 1
#
#                 self.update_replay_memory(state, action, reward, next_state, terminated, log_prob, value)
#
#                 state = torch.FloatTensor(next_state)
#
#             # Compute advantages and returns
#             _, last_value = self.model(state)
#             episode_values.append(last_value)
#             advantages, returns = self.compute_advantages(episode_rewards, episode_values, episode_dones)
#
#             # Ensure returns and episode_values are the same length
#             if len(returns) != len(episode_values) - 1:
#                 raise ValueError(
#                     f"Mismatch in lengths: returns({len(returns)}) vs episode_values({len(episode_values) - 1})")
#
#             # Initialize losses
#             policy_loss = torch.tensor(0.0)
#             value_loss = torch.tensor(0.0)
#             loss = torch.tensor(0.0)
#
#             # Training step
#             if len(self.replay_memory) >= self.batch_size:
#                 minibatch = random.sample(self.replay_memory, self.batch_size)
#                 states, actions, rewards_batch, next_states, dones, log_probs, values = zip(*minibatch)
#
#                 # Convert lists to tensors
#                 states = torch.stack([torch.FloatTensor(s) for s in states])
#                 actions = torch.LongTensor(actions)
#                 old_log_probs = torch.stack([lp.detach() for lp in log_probs])
#                 values = torch.stack([v.detach() for v in values])  # Detach values here
#
#                 # Recompute advantages for the sampled minibatch
#                 advantages_batch = []
#                 returns_batch = []
#                 for r, v, d in zip(rewards_batch, values, dones):
#                     adv, ret = self.compute_advantages([r], [v], [d])
#                     advantages_batch.append(adv)
#                     returns_batch.append(ret)
#
#                 advantages_batch = torch.cat(advantages_batch).detach()
#                 returns_batch = torch.cat(returns_batch).detach()
#
#                 # Ensure the shapes match
#                 if states.size(0) != advantages_batch.size(0):
#                     raise ValueError(
#                         f"Shape mismatch: states({states.size(0)}) vs advantages({advantages_batch.size(0)})")
#
#                 policy_dist, values = self.model(states)
#                 log_probs = torch.log(
#                     policy_dist.gather(1, actions.unsqueeze(1)).squeeze(1) + 1e-9)  # Add epsilon to avoid log(0)
#                 ratios = torch.exp(log_probs - old_log_probs)
#
#                 surr1 = ratios * advantages_batch
#                 surr2 = torch.clamp(ratios, 1 - self.epsilon, 1 + self.epsilon) * advantages_batch
#                 policy_loss = -torch.min(surr1, surr2).mean()
#                 value_loss = nn.MSELoss()(values.squeeze(), returns_batch)  # Ensure values are squeezed
#                 loss = policy_loss + value_loss
#
#                 self.optimizer.zero_grad()
#                 loss.backward(retain_graph=False)  # Ensure retain_graph is not used
#
#                 # Apply gradient clipping
#                 # torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
#
#                 self.optimizer.step()
#                 # scheduler.step()  # Update learning rate
#
#             # Update accumulators for visualization
#             actual_rewards.append(episode_rewards)
#             predicted_rewards.append([prob.item() for prob in episode_log_probs])
#             rewards_per_episode.append(np.mean(episode_rewards))
#
#             # Update the state visit counts
#             for state in visited_states:
#                 state_str = str(state)  # Convert the state to a string to use it as a dictionary key
#                 if state_str in visited_state_counts:
#                     visited_state_counts[state_str] += 1
#                 else:
#                     visited_state_counts[state_str] = 1
#
#             # Append the episode reward to the reward window for moving average calculation
#             self.reward_window.append(sum(episode_rewards))
#             moving_avg_reward = np.mean(self.reward_window)
#
#             # Prepare the log data
#             log_data = {
#                 "moving_avg_reward": moving_avg_reward,
#                 "episode": episode,
#                 "avg_reward": np.mean(episode_rewards),
#                 "total_reward": np.sum(episode_rewards),
#                 "exploration_rate": self.epsilon
#             }
#
#             # Add loss values to log data only if they were computed
#             if len(self.replay_memory) >= self.batch_size:
#                 log_data.update({
#                     "policy_loss": policy_loss.item(),
#                     "value_loss": value_loss.item(),
#                     "loss": loss.item(),
#                     "learning_rate": self.optimizer.param_groups[0]['lr']
#                 })
#
#             # Log all metrics to wandb once
#             wandb.log(log_data)
#             # if episode % 100 == 0:
#             self.epsilon = self.decay_handler.get_exploration_rate(episode)
#
#             pbar.update(1)
#             pbar.set_description(
#                 f"Policy Loss {float(policy_loss.item())} Value Loss {float(value_loss.item())} Avg R {float(np.mean(episode_rewards))}")
#
#         pbar.close()        # After training, save the model
#         model_file_path = os.path.join(self.model_subdirectory, 'model.pt')
#         torch.save(self.model.state_dict(), model_file_path)
#
#
#         # After training, visualize the state visitations
#         states = [list(state) for state in visited_state_counts.keys()]
#         visit_counts = list(visited_state_counts.values())
#
#         try:
#             states_visited_path = states_visited_viz(states, visit_counts, alpha, self.results_subdirectory)
#             if states_visited_path:
#                 wandb.log({"States Visited": wandb.Image(states_visited_path)})
#             else:
#                 print("Failed to generate states visited visualization")
#         except Exception as e:
#             print(f"Error in states_visited_viz: {e}")
#             # Log an error message to wandb
#             wandb.log({"States Visited Error": f"Failed to generate visualization: {e}"})
#
#         avg_rewards = [sum(lst) / len(lst) for lst in actual_rewards]
#         explained_variance_path = visualize_explained_variance(actual_rewards, predicted_rewards,
#                                                                self.results_subdirectory, self.max_episodes)
#         wandb.log({"Explained Variance": [wandb.Image(explained_variance_path)]})
#
#         # file_path_variance = visualize_variance_in_rewards(avg_rewards, self.results_subdirectory, self.max_episodes)
#         # wandb.log({"Variance in Rewards": [wandb.Image(file_path_variance)]})
#
#         saved_model = load_saved_model(self.model_directory, self.agent_type, self.run_name, self.timestamp,
#                                        self.input_dim, self.hidden_dim, self.output_dim)
#         value_range = range(0, 101, 10)
#         all_states = [np.array([i, j]) for i in value_range for j in value_range]
#         all_states_path = visualize_all_states(saved_model, all_states, self.run_name, self.max_episodes, alpha,
#                                                self.results_subdirectory)
#         wandb.log({"All_States_Visualization": [wandb.Image(all_states_path)]})
#
#         return rewards_per_episode
#
#     def train_single_run(self, alpha):
#         return self.train(alpha)
#
#     def multiple_runs(self, num_runs, alpha, beta):
#         """Run multiple training runs and visualize the tolerance intervals."""
#         all_returns = []
#
#         for run in range(num_runs):
#             print(f"Run {run + 1}/{num_runs}")
#             returns_per_episode = self.train_single_run(alpha)
#             all_returns.append(returns_per_episode)
#
#         output_path_mean = os.path.join(self.results_subdirectory, 'tolerance_interval_mean.png')
#         output_path_median = os.path.join(self.results_subdirectory, 'tolerance_interval_median.png')
#         self.visualize_tolerance_interval_curve(all_returns, alpha, beta, output_path_mean, metric='mean')
#         self.visualize_tolerance_interval_curve(all_returns, alpha, beta, output_path_median, metric='median')
#         wandb.log({"Tolerance Interval Mean": [wandb.Image(output_path_mean)],
#                    "Tolerance Interval Median": [wandb.Image(output_path_median)]})
#
#         # Confidence Intervals
#         confidence_alpha = 0.05  # 95% confidence interval
#         confidence_output_path = os.path.join(self.results_subdirectory, 'confidence_interval.png')
#         self.visualize_confidence_interval(returns_per_episode, confidence_alpha, confidence_output_path)
#         wandb.log({"Confidence Interval": [wandb.Image(confidence_output_path)]})
#
#         # Box Plot Confidence Intervals
#         boxplot_output_path = os.path.join(self.results_subdirectory, 'boxplot_confidence_interval.png')
#         self.visualize_boxplot_confidence_interval(returns_per_episode, confidence_alpha, boxplot_output_path)
#         wandb.log({"Box Plot Confidence Interval": [wandb.Image(boxplot_output_path)]})
#
#     def visualize_tolerance_interval_curve(self, returns, alpha, beta, output_path, metric='mean'):
#         """
#         Visualize the (alpha, beta)-tolerance interval curve over episodes for mean or median performance.
#
#         Parameters:
#         returns (list): The list of returns per episode across multiple runs.
#         alpha (float): The nominal error rate (e.g., 0.05 for 95%).
#         beta (float): The proportion of future samples to be captured (e.g., 0.9 for 90%).
#         output_path (str): The file path to save the plot.
#         metric (str): The metric to visualize ('mean' or 'median').
#         """
#         lower_bounds = []
#         upper_bounds = []
#         central_tendency = []
#         episodes = list(range(len(returns[0])))  # Assume all runs have the same number of episodes
#
#         for episode in episodes:
#             episode_returns = [returns[run][episode] for run in range(len(returns))]
#             flattened_returns = np.array(episode_returns)  # Convert to numpy array
#             if metric == 'mean':
#                 performance = np.mean(flattened_returns)
#             elif metric == 'median':
#                 performance = np.median(flattened_returns)
#             else:
#                 raise ValueError("Invalid metric specified. Use 'mean' or 'median'.")
#
#             lower, upper = self.compute_tolerance_interval(flattened_returns, alpha, beta)
#             lower_bounds.append(lower)
#             upper_bounds.append(upper)
#             central_tendency.append(performance)
#
#         plt.figure(figsize=(10, 6))
#         sns.lineplot(x=episodes, y=central_tendency, label=f'{metric.capitalize()} Performance', color='b')
#         plt.fill_between(episodes, lower_bounds, upper_bounds, color='gray', alpha=0.2,
#                          label=f'Tolerance Interval (α={alpha}, β={beta})')
#         plt.title(f'Tolerance Interval Curve for {metric.capitalize()} Performance')
#         plt.xlabel('Episode')
#         plt.ylabel('Return')
#         plt.legend()
#         plt.savefig(output_path)
#         plt.close()
#
#     def compute_tolerance_interval(self, data, alpha, beta):
#         """
#         Compute the (alpha, beta)-tolerance interval for a given data sample.
#
#         Parameters:
#         data (list or numpy array): The data sample.
#         alpha (float): The nominal error rate (e.g., 0.05 for 95%).
#         beta (float): The proportion of future samples to be captured (e.g., 0.9 for 90%).
#
#         Returns:
#         (float, float): The lower and upper bounds of the tolerance interval.
#         """
#         n = len(data)
#         sorted_data = np.sort(data)
#
#         # Compute the number of samples that do not belong to the middle beta proportion
#         nu = stats.binom.ppf(1 - alpha, n, beta)
#
#         # Compute the indices for the lower and upper bounds
#         l = int(np.floor(nu / 2))
#         u = int(np.ceil(n - nu / 2))
#
#         return sorted_data[l], sorted_data[u]
#
#     def compute_confidence_interval(self, data, alpha):
#         """
#         Compute the confidence interval for a given data sample using the Student t-distribution.
#
#         Parameters:
#         data (list or numpy array): The data sample.
#         alpha (float): The nominal error rate (e.g., 0.05 for 95% confidence interval).
#
#         Returns:
#         (float, float): The lower and upper bounds of the confidence interval.
#         """
#         n = len(data)
#         mean = np.mean(data)
#         std_err = np.std(data, ddof=1) / np.sqrt(n)
#         t_value = stats.t.ppf(1 - alpha / 2, df=n - 1)
#         margin_of_error = t_value * std_err
#         return mean - margin_of_error, mean + margin_of_error
#
#     def visualize_confidence_interval(self, returns, alpha, output_path):
#         """
#         Visualize the confidence interval over episodes.
#
#         Parameters:
#         returns (list): The list of returns per episode across multiple runs.
#         alpha (float): The nominal error rate (e.g., 0.05 for 95% confidence interval).
#         output_path (str): The file path to save the plot.
#         """
#         means = []
#         lower_bounds = []
#         upper_bounds = []
#         episodes = list(range(len(returns[0])))  # Assume all runs have the same number of episodes
#
#         for episode in episodes:
#             episode_returns = [returns[run][episode] for run in range(len(returns))]
#             mean = np.mean(episode_returns)
#             lower, upper = self.compute_confidence_interval(episode_returns, alpha)
#             means.append(mean)
#             lower_bounds.append(lower)
#             upper_bounds.append(upper)
#
#         plt.figure(figsize=(10, 6))
#         sns.lineplot(x=episodes, y=means, label='Mean Performance', color='b')
#         plt.fill_between(episodes, lower_bounds, upper_bounds, color='gray', alpha=0.2,
#                          label=f'Confidence Interval (α={alpha})')
#         plt.title(f'Confidence Interval Curve for Mean Performance')
#         plt.xlabel('Episode')
#         plt.ylabel('Return')
#         plt.legend()
#         plt.savefig(output_path)
#         plt.close()
#
#     def visualize_boxplot_confidence_interval(self, returns, alpha, output_path):
#         """
#         Visualize the confidence interval using box plots.
#
#         Parameters:
#         returns (list): The list of returns per episode across multiple runs.
#         alpha (float): The nominal error rate (e.g., 0.05 for 95% confidence interval).
#         output_path (str): The file path to save the plot.
#         """
#         episodes = list(range(len(returns[0])))  # Assume all runs have the same number of episodes
#         returns_transposed = np.array(returns).T.tolist()  # Transpose to get returns per episode
#
#         plt.figure(figsize=(12, 8))
#         sns.boxplot(data=returns_transposed, whis=[100 * alpha / 2, 100 * (1 - alpha / 2)])
#         plt.title(f'Box Plot of Returns with Confidence Interval (α={alpha})')
#         plt.xlabel('Run')
#         plt.ylabel('Return')
#         plt.xticks(ticks=range(len(episodes)), labels=episodes)
#         plt.savefig(output_path)
#         plt.close()
#
#
#
#
# def load_saved_model(model_directory, agent_type, run_name, timestamp, input_dim, hidden_dim, action_space_nvec):
#     """
#     Load a saved ActorCriticNetwork model from the subdirectory.
#
#     Args:
#     model_directory: Base directory where models are stored.
#     agent_type: Type of the agent, used in directory naming.
#     run_name: Name of the run, used in directory naming.
#     timestamp: Timestamp of the model saving time, used in directory naming.
#     input_dim: Input dimension of the model.
#     hidden_dim: Hidden layer dimension.
#     action_space_nvec: Action space vector size.
#
#     Returns:
#     model: The loaded ActorCriticNetwork model, or None if loading failed.
#     """
#     # Construct the model subdirectory path
#     model_subdirectory = os.path.join(model_directory, agent_type, run_name, timestamp)
#
#     # Construct the model file path
#     model_file_path = os.path.join(model_subdirectory, 'model.pt')
#
#     # Check if the model file exists
#     if not os.path.exists(model_file_path):
#         print(f"Model file not found in {model_file_path}")
#         return None
#
#     # Initialize a new model instance
#     model = ActorCriticNetwork(input_dim, hidden_dim, action_space_nvec)
#
#     # Load the saved model state into the model instance
#     model.load_state_dict(torch.load(model_file_path))
#     model.eval()  # Set the model to evaluation mode
#
#     return model
