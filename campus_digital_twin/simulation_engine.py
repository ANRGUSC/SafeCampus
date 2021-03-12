import yaml
import os
from campus_digital_twin import campus_state as cs
from campus_digital_twin import infection_modela as im

def load_sim_params(params_yaml):
    with open(params_yaml, 'r') as stream:
        try:
            sim_params = yaml.safe_load(stream)
            # print(yaml.safe_load(stream))
        except yaml.YAMLError as exc:
            print(exc)

    return sim_params

def search_sim_params(params_list_of_dict, search_string):
    """
    :param params_list_of_dict:
    :param search_string:
    :return: list
    """
    data_list = []
    for i in params_list_of_dict:
        [[key, value]] = i.items()
        my_list = key.split("_")
        if search_string in my_list:
            data_list.append(i)

    return data_list
#
#
def generate_infection_list(list_of_dict):
    """
    :param -> list_of_dict:
    :return:
    """
    total = list_of_dict[0].values
    status_list = []
    for status in list_of_dict[1:]:
        for key, value in status.items():
            if value == 0 or value < 0:
                pass
            else:
                infection_status = [key] * value
                status_list = status_list + infection_status

    return status_list, total

def create_campus_state():
#    sim_params = load_sim_params('campus_digital_twin/simulator_params.yaml')
#    sim_params = load_sim_params('/home/runner/planR-7/campus_digital_twin/simulator_params.yaml')
    sim_params = load_sim_params(os.path.dirname(os.path.realpath(__file__))+'/simulator_params.yaml')
    student_status = generate_infection_list(search_sim_params(sim_params, 'students'))
    teacher_status = generate_infection_list(search_sim_params(sim_params, 'teachers'))
    course_quarantine_status = search_sim_params(sim_params, 'course')
    shut_down = list(search_sim_params(sim_params, 'shutdown')[0].values())[0]
    community_risk = list(search_sim_params(sim_params, 'community')[0].values())[0]
#    course_operation_status = [];
    #campus_state_obj = campus_state.CampusState(True, student_status, teacher_status, course_quarantine_status,
    # #                                            shut_down,
    #                                             community_risk)
#    print(campus_state.testNumber)
    campus_state_obj = cs.CampusState(True, student_status, teacher_status, course_quarantine_status,
                        shut_down, community_risk)

    return campus_state_obj


# def get_action():
#     infection_status = im.InfectionModel(number_of_students_per_course=[10, 10, 10, 10], community_risk=0.5)
#     return infection_status.get_infected_students()


