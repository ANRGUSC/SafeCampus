import gym
from gym import error, spaces, utils
from gym.utils import seeding
from campus_digital_twin import campus_model as cm
from campus_digital_twin import campus_state as cs
from campus_digital_twin import simulation_engine as se

# from campus_digital_twin import observations, simulation_engine, scheduler
class CampusGymEnv(gym.Env):
    metadata = {'render.modes': ['human']}
    # temporarily say that the state is
    state = []
    csobject = None

    def __init__(self):

        # need to figure out how to read these from campus_model or parameters from digital twin
        # num_classes = 4

        #        cmodel = cm.CampusModel()
        # self.csobject = cs.CampusState()
        self.csobject = se.create_campus_state()

        num_classes = self.csobject.model.total_courses()

        print("num classes =  " + str(num_classes))
        num_infec_levels = 10
        num_occup_levels = 3

        self.action_space = gym.spaces.MultiDiscrete([num_occup_levels for _ in range(num_classes)])
        self.observation_space = gym.spaces.MultiDiscrete([num_infec_levels for _ in range(num_classes + 1)])

        self.state = [1, 1, 1, 1, 1]

        # self.action_space = gym.spaces.Dict(scheduler.CourseRoomScheduler().get_schedule())
        # self.observation_space = gym.spaces.Discrete()

    def step(self, action):
        # state = self.observation_space
        # action = self.action_space
        """
        This is an example:
        -
        """
        # naive model of infection here: for each class, see if class is scheduled
        # half or full occupancy, and accordingly increase infections

        # self.csobject.update_with_action(action)
        # self.csobject.update_with_models()
        # observation = self.csobject.get_observation()
        # reward = self.csobject.get_reward()
        # some logic to check if done
        # return the above observation, reward, done, info

        observation = self.observation_space

        # we should be using hte simulation engine to
        # get the reward, state update and observation
        reward = 20
        for i in range(4):
          if action[i] == 2:
            self.state[i] += 2
            reward -= 4

          if action[i] == 1:
            self.state[i] += 1
            reward -= 2
          observation.nvec[i] = self.state[i]

        # if action == [10, 20, 30, 40]:
        #     reward = 1
        # else:
        #     reward = -1
        done = False
        info = {}

        return observation, reward, done, info

    def reset(self):

        #state = simulation_engine.create_campus_state()
        self.state = [1,1,1,1]
        #return sestate

    def render(self, mode='human', close=False):
        print(self.state)
        return

