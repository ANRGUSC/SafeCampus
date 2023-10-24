import numpy as np
import itertools
from .utilities import load_config
from .visualizer import visualize_all_states, visualize_q_table, visualize_variance_in_rewards_heatmap, \
    visualize_explained_variance, visualize_variance_in_rewards
import os
import io
import json
import logging
from datetime import datetime
from tqdm import tqdm
import wandb
import random


class QLearningAgent:
    def __init__(self, env, run_name, shared_config_path, agent_config_path):
        # Load Shared Config
        self.shared_config = load_config(shared_config_path)

        # Load Agent Specific Config
        self.agent_config = load_config(agent_config_path)

        # Access the results directory from the shared_config
        self.results_directory = self.shared_config['directories']['results_directory']

        # Create a unique subdirectory for each run to avoid overwriting results
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.results_subdirectory = os.path.join(self.results_directory, run_name, timestamp)
        os.makedirs(self.results_subdirectory, exist_ok=True)

        # Set up logging to the correct directory
        log_file_path = os.path.join(self.results_subdirectory, 'agent_log.txt')
        logging.basicConfig(filename=log_file_path, level=logging.INFO)
        # Initialize agent-specific configurations and variables
        self.env = env
        self.run_name = run_name
        self.max_episodes = self.agent_config['agent']['max_episodes']
        self.learning_rate = self.agent_config['agent']['learning_rate']
        self.discount_factor = self.agent_config['agent']['discount_factor']
        self.exploration_rate = self.agent_config['agent']['exploration_rate']
        self.min_exploration_rate = self.agent_config['agent']['min_exploration_rate']
        self.exploration_decay_rate = self.agent_config['agent']['exploration_decay_rate']

        # Initialize q table
        rows = np.prod(env.observation_space.nvec)
        columns = np.prod(env.action_space.nvec)
        self.q_table = np.zeros((rows, columns))

        # Initialize other required variables and structures
        self.training_data = []
        self.possible_actions = [list(range(0, (k))) for k in self.env.action_space.nvec]
        self.possible_states = [list(range(0, (k))) for k in self.env.observation_space.nvec]
        self.all_actions = [str(i) for i in list(itertools.product(*self.possible_actions))]
        self.all_states = [str(i) for i in list(itertools.product(*self.possible_states))]
        self.states = list(itertools.product(*self.possible_states))

        # moving average for early stopping criteria
        self.moving_average_window = 50  # Number of episodes to consider for moving average
        self.stopping_criterion = 0.01  # Threshold for stopping

    def _policy(self, mode, state):
        """Define the policy of the agent."""
        global action
        if mode == 'train':
            if random.uniform(0, 1) > self.exploration_rate:
                # print("Non random action selected", self.exploration_rate)
                dstate = str(tuple(state))
                action = np.argmax(self.q_table[self.all_states.index(dstate)])

            else:
                sampled_actions = str(tuple(self.env.action_space.sample().tolist()))
                # print("sampled action", sampled_actions, self.exploration_rate)

                action = self.all_actions.index(sampled_actions)
                # print("Action chosen", action)

        elif mode == 'test':
            dstate = str(tuple(state))
            action = np.argmax(self.q_table[self.all_states.index(dstate)])

        return action

    def train(self, alpha):
        """Train the agent."""
        # reset Q table
        rows = np.prod(self.env.observation_space.nvec)
        columns = np.prod(self.env.action_space.nvec)
        self.q_table = np.zeros((rows, columns))

        state_transition_dict = {}
        mean_eps_returns = []
        actual_rewards = []
        predicted_rewards = []
        rewards = []
        rewards_per_episode = []

        for episode in tqdm(range(self.max_episodes)):
            # print(f"+-------- Episode: {episode} -----------+")
            state = self.env.reset()
            c_state = state[0]
            terminated = False
            e_return = []
            e_allowed = []
            e_infected_students = []
            actions_taken_until_done = []
            state_transitions = []
            total_reward = 0
            e_predicted_rewards = []

            while not terminated:
                # Select an action using the current state and the policy
                action = self._policy('train', c_state)
                converted_state = str(tuple(c_state))
                state_idx = self.all_states.index(converted_state)  # Define state_idx here

                list_action = list(eval(self.all_actions[action]))
                c_list_action = [i * 50 for i in list_action]
                action_alpha_list = [*c_list_action, alpha]

                # Execute the action and observe the next state and reward
                next_state, reward, terminated, _, info = self.env.step(action_alpha_list)

                # Update the Q-table using the observed reward and the maximum future value
                old_value = self.q_table[self.all_states.index(converted_state), action]
                next_max = np.max(self.q_table[self.all_states.index(str(tuple(next_state)))])
                new_value = (1 - self.learning_rate) * old_value + self.learning_rate * (
                            reward + self.discount_factor * next_max)
                self.q_table[self.all_states.index(converted_state), action] = new_value
                # Store predicted reward (Q-value) for the taken action
                predicted_reward = self.q_table[state_idx, action]
                e_predicted_rewards.append(predicted_reward)

                # Log the state transition
                state_transitions.append((state, next_state))

                # Update the state to the next state
                state = next_state

                # Update other accumulators...
                week_reward = int(reward)
                total_reward += week_reward
                e_return.append(week_reward)
                e_allowed = info['allowed']
                e_infected_students = info['infected']
                actions_taken_until_done.append(list_action)
                state_transitions.append((state, next_state))
                # print("allowed: ", e_allowed, "infected: ", e_infected_students, "reward: ", week_reward)

                # Log state, action, and Q-values.
                logging.info(f"State: {state}, Action: {action}, Q-values: {self.q_table[state_idx, :]}")

            avg_episode_return = sum(e_return) / len(e_return)
            rewards_per_episode.append(avg_episode_return)
            if episode % self.agent_config['agent']['checkpoint_interval'] == 0:
                checkpoint_path = os.path.join(self.results_subdirectory, f"qtable-{episode}-qtable.npy")
                np.save(checkpoint_path, self.q_table)

                # Call the visualizers functions here
                visualize_q_table(self.q_table, self.results_subdirectory, episode)
                # Example usage:
            # If enough episodes have been run, check for convergence
            if episode >= self.moving_average_window - 1:
                window_rewards = rewards_per_episode[max(0, episode - self.moving_average_window + 1):episode + 1]
                moving_avg = np.mean(window_rewards)
                std_dev = np.std(window_rewards)

                # Log the moving average and standard deviation along with the episode number
                wandb.log({
                    'Moving Average': moving_avg,
                    'Standard Deviation': std_dev,
                    'average_return': total_reward/len(e_return),
                    'step': episode  # Ensure the x-axis is labeled correctly as 'Episodes'
                })

                # If the standard deviation is below the threshold, stop training
                if std_dev < self.stopping_criterion:
                    print(f"Training converged at episode {episode}. Stopping training.")
                    break

            logging.info(f"Episode: {episode}, Length: {len(e_return)}, Cumulative Reward: {sum(e_return)}, "
                         f"Exploration Rate: {self.exploration_rate}")

            # Render the environment at the end of each episode
            if episode % self.agent_config['agent']['checkpoint_interval'] == 0:
                self.env.render()
            predicted_rewards.append(e_predicted_rewards)
            actual_rewards.append(e_return)
            self.exploration_rate = max(self.min_exploration_rate, self.exploration_rate * self.exploration_decay_rate)

        print("Training complete.")
        avg_rewards = [sum(lst) / len(lst) for lst in actual_rewards]
        # Pass actual and predicted rewards to visualizer
        explained_variance_path = visualize_explained_variance(actual_rewards, predicted_rewards, self.results_subdirectory, self.max_episodes)
        wandb.log({"Explained Variance": [wandb.Image(explained_variance_path)]})


        file_path_variance = visualize_variance_in_rewards(avg_rewards, self.results_subdirectory, self.max_episodes)
        wandb.log({"Variance in Rewards": [wandb.Image(file_path_variance)]})

        # Inside the train method, after training the agent:
        all_states_path = visualize_all_states(self.q_table, self.all_states, self.states, self.run_name, self.max_episodes, alpha,
                            self.results_subdirectory)
        wandb.log({"All_States_Visualization": [wandb.Image(all_states_path)]})
        file_path_heatmap = visualize_variance_in_rewards_heatmap(rewards_per_episode, self.results_subdirectory, bin_size=10)
        wandb.log({"Variance in Rewards Heatmap": [wandb.Image(file_path_heatmap)]})

        return self.training_data